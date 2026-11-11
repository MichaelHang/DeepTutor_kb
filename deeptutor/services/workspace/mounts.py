"""Read-only folder mounts for a content workspace.

A mount lets the user hand one local folder to the agent without turning the
whole workspace into that folder: the folder keeps its own place on disk, and
the agent reaches it under a short logical name. Nothing about a mount is
writable — anything the agent produces still belongs in the workspace's
``outputs/`` — so a mount is a *view*, not a second root.

The logical path of a mounted file is ``<mount name>/<path inside the mount>``.
The host path behind a mount is runtime-only: it never reaches model messages,
public URLs, or persisted message metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable

from deeptutor.services.workspace.models import WorkspaceError

#: A mount name becomes a path prefix, so it stays a plain, short segment.
MOUNT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

#: One workspace may not mount an unbounded number of folders.
MAX_MOUNTS = 16

#: Names the workspace itself already uses. A mount may not shadow them.
RESERVED_MOUNT_NAMES = frozenset({"outputs", ".deeptutor"})


@dataclass(frozen=True, slots=True)
class WorkspaceMount:
    """One folder the agent may read through a logical name."""

    name: str
    path: Path

    @property
    def read_only(self) -> bool:
        """Mounts are views. There is no writable mount."""
        return True

    def public_dict(self) -> dict[str, Any]:
        """Describe the mount to its owner, who chose the folder themselves."""
        return {"name": self.name, "path": str(self.path), "read_only": True}

    def runtime_dict(self) -> dict[str, Any]:
        """Describe the mount inside the turn runtime, never to the model."""
        return {"name": self.name, "path": str(self.path)}

    def logical_path(self, path: str | Path) -> str:
        """Return the logical path of ``path`` inside this mount."""
        candidate = Path(path).resolve()
        try:
            relative = candidate.relative_to(self.path)
        except ValueError as exc:
            raise WorkspaceError("The path is outside the mounted folder.") from exc
        rest = "/".join(relative.parts)
        return f"{self.name}/{rest}" if rest else self.name


def parse_mounts(raw: Any, *, skip_unavailable: bool = False) -> list[WorkspaceMount]:
    """Validate stored or submitted mount definitions.

    The definitions come from the workspace registry and from session
    preferences, so they are validated on every read rather than trusted.
    ``skip_unavailable`` drops a mount whose folder has gone away instead of
    failing the whole list — a renamed folder must not break the workspace.
    """
    if raw in (None, "", [], {}):
        return []
    if not isinstance(raw, list):
        raise WorkspaceError("Mounts must be a list of folders.")
    if len(raw) > MAX_MOUNTS:
        raise WorkspaceError(f"A workspace can mount at most {MAX_MOUNTS} folders.")
    mounts: list[WorkspaceMount] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise WorkspaceError("Each mount must name a folder.")
        name = str(entry.get("name") or "").strip()
        if not MOUNT_NAME_RE.fullmatch(name):
            raise WorkspaceError(
                "A mount name must start with a letter or digit and may only contain "
                "letters, digits, dots, dashes or underscores."
            )
        if name.lower() in RESERVED_MOUNT_NAMES:
            raise WorkspaceError(f"“{name}” is reserved and cannot be used as a mount name.")
        if name in seen:
            raise WorkspaceError(f"Two mounts share the name “{name}”.")
        seen.add(name)
        raw_path = str(entry.get("path") or "").strip()
        if not raw_path:
            raise WorkspaceError("Each mount needs a folder path.")
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            raise WorkspaceError("A mount must point at an absolute folder.")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            if skip_unavailable:
                continue
            raise WorkspaceError(f"The mounted folder is unavailable: {raw_path}") from exc
        if not resolved.is_dir():
            if skip_unavailable:
                continue
            raise WorkspaceError("A mount must point at a folder.")
        mounts.append(WorkspaceMount(name=name, path=resolved))
    return mounts


def describe_mounts(raw: Any) -> list[dict[str, Any]]:
    """Describe stored mount definitions to their owner.

    A folder that has gone away is reported as unavailable rather than
    hidden: the owner has to see which mount stopped working.
    """
    if not isinstance(raw, list):
        return []
    described: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        path = str(entry.get("path") or "").strip()
        if not name or not path:
            continue
        available = Path(path).expanduser().is_dir()
        described.append({"name": name, "path": path, "read_only": True, "available": available})
    return described


def mount_map(mounts: Iterable[WorkspaceMount]) -> dict[str, WorkspaceMount]:
    """Index mounts by their logical name."""
    return {mount.name: mount for mount in mounts}


def mounts_to_rows(mounts: Iterable[WorkspaceMount]) -> list[dict[str, Any]]:
    """Serialize mounts for the workspace registry row."""
    return [{"name": mount.name, "path": str(mount.path)} for mount in mounts]


def mounts_to_runtime(mounts: Iterable[WorkspaceMount]) -> list[dict[str, Any]]:
    """Serialize mounts for the turn runtime context."""
    return [mount.runtime_dict() for mount in mounts]


__all__ = [
    "MAX_MOUNTS",
    "MOUNT_NAME_RE",
    "RESERVED_MOUNT_NAMES",
    "WorkspaceMount",
    "describe_mounts",
    "mount_map",
    "mounts_to_rows",
    "mounts_to_runtime",
    "parse_mounts",
]
