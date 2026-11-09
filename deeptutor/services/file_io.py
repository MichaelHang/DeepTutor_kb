"""Small, dependency-free helpers for durable service files."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# fsync failures weaken the durability promise but do not corrupt the write:
# the replacement below still publishes complete content. Warn about them,
# rate-limited, so a failing disk fills the log once per interval instead of
# once per write.
_FSYNC_WARNING_INTERVAL_SECONDS = 60.0
_last_fsync_warning_at: float | None = None
_fsync_warning_lock = threading.Lock()


def _sync_to_disk(handle: Any, path: Path) -> None:
    """fsync *handle*, surfacing a failure as a rate-limited warning."""
    global _last_fsync_warning_at
    try:
        os.fsync(handle.fileno())
    except OSError as exc:
        now = time.monotonic()
        with _fsync_warning_lock:
            should_warn = (
                _last_fsync_warning_at is None
                or now - _last_fsync_warning_at >= _FSYNC_WARNING_INTERVAL_SECONDS
            )
            if should_warn:
                _last_fsync_warning_at = now
        if should_warn:
            logger.warning(
                "fsync failed while writing %s; the write succeeded but is not"
                " guaranteed durable on disk (%r)",
                path,
                exc,
            )


def _retry_permission_error(operation: Callable[[], T], *, max_retries: int) -> T:
    """Run *operation*, retrying a transient ``PermissionError`` with backoff.

    On Windows a file is occasionally locked by another process (antivirus,
    indexer, or a concurrent reader), which makes opening or replacing it
    raise ``PermissionError``. A short exponential backoff recovers in most
    cases; a lock that outlasts it is re-raised unchanged.
    """
    delay = 0.2
    for attempt in range(max_retries):
        try:
            return operation()
        except PermissionError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 1.6)
    raise ValueError("max_retries must be at least 1")


def _atomic_replace(src: Path, dst: Path, *, max_retries: int = 5) -> None:
    """Replace *dst* with *src*, retrying on transient ``PermissionError``."""
    _retry_permission_error(lambda: src.replace(dst), max_retries=max_retries)


def read_text(path: Path, *, max_retries: int = 5) -> str:
    """Read a UTF-8 file written by the atomic helpers below.

    Reads use the writers' encoding instead of the locale default, and a
    transient Windows sharing lock gets the same bounded retry as writes.
    ``FileNotFoundError`` and decoding errors propagate immediately.
    """
    path = Path(path)
    return _retry_permission_error(
        lambda: path.read_text(encoding="utf-8"), max_retries=max_retries
    )


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write *payload* as UTF-8 JSON without exposing a partial target file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            _sync_to_disk(handle, path)
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    """Write UTF-8 text with a same-directory atomic replacement."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(path.parent),
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            _sync_to_disk(handle, path)
        _atomic_replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def is_hardlinked(path: Path) -> bool:
    """True when *path* shares its inode with another name on disk.

    A hard link is a second directory entry for the same bytes, so such a file
    is not an independent copy: writing through it would rewrite the file it
    was linked from. ``st_nlink`` counts the directory entries for the inode,
    which is exactly what tells the two apart.
    """
    try:
        return path.stat().st_nlink > 1
    except OSError:
        return False


def detach_if_hardlinked(path: Path) -> bool:
    """Drop *path*'s directory entry when it is a hard link.

    Replacing the entry — rather than the bytes behind it — breaks the link
    without touching the file it came from, so whatever is written next lands
    in a new, independent file instead of overwriting the original. Returns
    True when an entry was removed.
    """
    if not is_hardlinked(path):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def link_or_copy(source: Path, dest: Path) -> bool:
    """Put *source* at *dest*, sharing the bytes when the filesystem allows it.

    A hard link keeps a single copy of the data on disk, so a document staged
    from a linked folder stays in step with the original instead of drifting
    away from it. Hard links cannot cross a filesystem boundary, and some
    volumes refuse them outright, so a plain copy is made whenever the link is
    rejected. Returns True when the two names ended up sharing one inode.
    """
    try:
        os.link(source, dest)
        return True
    except OSError:
        shutil.copy2(source, dest)
        return False


__all__ = [
    "atomic_write_json",
    "atomic_write_text",
    "detach_if_hardlinked",
    "is_hardlinked",
    "link_or_copy",
    "read_text",
]
