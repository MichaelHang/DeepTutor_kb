"""Persistence of linked-folder sync state (``metadata.json``).

``update_folder_sync_state()`` used to mutate the loaded metadata dict and
return without writing it back, so ``last_sync``/``synced_files`` silently
vanished while the API layer logged success. These tests pin the write-back.
The atomicity contract of the shared writer lives in
``tests/services/test_file_io.py``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from deeptutor.api.routers.knowledge import LinkedFolderInfo
from deeptutor.knowledge import manager as manager_module
from deeptutor.knowledge.manager import KnowledgeBaseManager


def _manager_with_linked_folder(tmp_path: Path) -> tuple[KnowledgeBaseManager, Path, str, Path]:
    """A registered KB with one linked folder containing one markdown file."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))

    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    source.mkdir()
    doc = source / "note.md"
    doc.write_text("hello", encoding="utf-8")

    folder_info = manager.link_folder("kb", str(source))
    assert folder_info["last_sync"] is None
    return manager, kb_dir / "metadata.json", folder_info["id"], doc


def test_update_folder_sync_state_persists_to_disk(tmp_path: Path) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    folder = on_disk["linked_folders"][0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]
    assert folder["file_count"] == 1

    # A fresh manager (new process in real life) must see the sync state too.
    reloaded = KnowledgeBaseManager(base_dir=str(manager.base_dir))
    folder = reloaded.get_linked_folders("kb")[0]
    assert "last_sync" in folder
    assert str(doc) in folder["synced_files"]

    info = LinkedFolderInfo(**folder)
    assert info.last_sync == folder["last_sync"]


def test_update_folder_sync_state_unknown_folder_writes_nothing(tmp_path: Path) -> None:
    manager, metadata_file, _folder_id, doc = _manager_with_linked_folder(tmp_path)
    before = metadata_file.read_bytes()

    manager.update_folder_sync_state("kb", "no-such-id", [str(doc)])

    assert metadata_file.read_bytes() == before


def test_sync_snapshot_preserves_change_made_during_indexing(tmp_path: Path) -> None:
    manager, _metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    staged_mtime = "2026-09-01T10:00:00"
    manager.update_folder_sync_state("kb", folder_id, [str(doc)], {str(doc): staged_mtime})

    changes = manager.detect_folder_changes("kb", folder_id)
    assert changes["modified_files"] == [str(doc)]


def test_empty_successful_sync_records_last_sync_without_changing_file_state(
    tmp_path: Path,
) -> None:
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    manager.update_folder_sync_state("kb", folder_id, [str(doc)])
    before = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]

    manager.update_folder_sync_state("kb", folder_id, [])

    after = json.loads(metadata_file.read_text(encoding="utf-8"))["linked_folders"][0]
    assert after["last_sync"]
    assert after["last_sync"] >= before["last_sync"]
    assert after["synced_files"] == before["synced_files"]


def test_update_folder_sync_state_mtime_failure_is_visible_not_fake_synced(
    tmp_path: Path,
    caplog,
    monkeypatch,
) -> None:
    """A per-file mtime recording failure must surface, not vanish.

    ``update_folder_sync_state()`` used to swallow stat/fromtimestamp errors
    with ``except Exception: pass``. The sync then reported success while the
    file's state was never recorded, hiding the degradation. The failure must
    be logged and the file must stay un-recorded so the next scan re-syncs it.
    """
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)

    flavour = type(Path())  # PosixPath on POSIX, WindowsPath on Windows

    class _VanishedMidStatPath(flavour):
        """exists() wins the race, stat() loses it (source vanished mid-sync)."""

        def exists(self, **kwargs):
            return True

        def stat(self, **kwargs):
            raise OSError("source vanished before stat")

    monkeypatch.setattr(manager_module, "Path", _VanishedMidStatPath)

    with caplog.at_level(logging.WARNING, logger="deeptutor.knowledge.manager"):
        manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    # Visibility: the swallowed failure is now a logged warning naming the file.
    warnings_for_doc = [
        record
        for record in caplog.records
        if record.levelno >= logging.WARNING and str(doc) in record.getMessage()
    ]
    assert warnings_for_doc, f"expected a logged warning mentioning {doc}, got none"

    # Fallback semantics: the file is not marked synced, so the next scan
    # re-detects it instead of trusting a fabricated "already synced" state.
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    folder = on_disk["linked_folders"][0]
    assert folder["last_sync"]
    assert str(doc) not in folder["synced_files"]
    assert folder["file_count"] == 0
    assert manager.detect_folder_changes("kb", folder_id)["new_files"] == [str(doc)]


def test_unlink_removes_the_link_and_the_documents_it_imported(tmp_path: Path) -> None:
    """Unlinking must not strand the copies the folder brought in.

    Only the link keeps those copies in sync, so leaving them behind would
    leave documents that nothing could refresh or remove afterwards.
    """
    manager, _metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    kb_dir = manager.base_dir / "kb"
    raw_file = kb_dir / "raw" / "note.md"
    uploaded = kb_dir / "raw" / "uploaded.md"
    index_marker = kb_dir / "version-1" / "index.marker"
    raw_file.parent.mkdir(parents=True)
    index_marker.parent.mkdir(parents=True)
    raw_file.write_text("imported", encoding="utf-8")
    uploaded.write_text("uploaded", encoding="utf-8")
    index_marker.write_text("index", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    result = manager.unlink_folder("kb", folder_id)

    assert result is not None
    assert result["removed_count"] == 1
    assert result["removed_files"] == ["note.md"]
    assert manager.get_linked_folders("kb") == []
    assert not raw_file.exists()
    assert uploaded.read_text(encoding="utf-8") == "uploaded"
    assert index_marker.read_text(encoding="utf-8") == "index"


def test_unlink_removes_documents_from_nested_folders(tmp_path: Path) -> None:
    """A folder's subdirectory structure is what identifies its staged copies."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    (source / "sub").mkdir(parents=True)
    doc = source / "sub" / "note.md"
    doc.write_text("hello", encoding="utf-8")
    folder_info = manager.link_folder("kb", str(source))

    staged = kb_dir / "raw" / "sub" / "note.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("imported", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_info["id"], [str(doc)])

    result = manager.unlink_folder("kb", folder_info["id"])

    assert result is not None
    assert result["removed_files"] == ["sub/note.md"]
    assert not staged.exists()


def test_unlink_removes_a_document_renamed_in_the_source_after_the_sync(
    tmp_path: Path,
) -> None:
    """A source file renamed after the sync keeps its old name in ``raw/``.

    The staged copy is still the folder's document, so unlinking has to find
    it by content — otherwise it stays behind as an orphan.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    source.mkdir()
    doc = source / "note.md"
    doc.write_text("hello", encoding="utf-8")
    folder_info = manager.link_folder("kb", str(source))

    staged = kb_dir / "raw" / "old-name.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("hello", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_info["id"], [str(doc)])

    renamed = source / "new-name.md"
    doc.rename(renamed)
    manager.update_folder_sync_state("kb", folder_info["id"], [str(renamed)])

    result = manager.unlink_folder("kb", folder_info["id"])

    assert result is not None
    assert result["removed_files"] == ["old-name.md"]
    assert not staged.exists()


def test_unlink_keeps_an_ambiguous_copy_that_also_exists_as_a_direct_upload(
    tmp_path: Path,
) -> None:
    """Identical content under two names is ambiguous, so neither is deleted."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    source.mkdir()
    doc = source / "note.md"
    doc.write_text("hello", encoding="utf-8")
    folder_info = manager.link_folder("kb", str(source))

    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "old-name.md").write_text("hello", encoding="utf-8")
    (raw_dir / "uploaded.md").write_text("hello", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_info["id"], [str(doc)])

    renamed = source / "new-name.md"
    doc.rename(renamed)
    manager.update_folder_sync_state("kb", folder_info["id"], [str(renamed)])

    result = manager.unlink_folder("kb", folder_info["id"])

    assert result is not None
    assert result["removed_files"] == []
    assert (raw_dir / "old-name.md").exists()
    assert (raw_dir / "uploaded.md").exists()


def test_unlink_drops_the_hash_records_of_the_removed_documents(tmp_path: Path) -> None:
    """The index hash record must go too, or a later re-add is skipped."""
    manager, metadata_file, folder_id, doc = _manager_with_linked_folder(tmp_path)
    kb_dir = manager.base_dir / "kb"
    raw_file = kb_dir / "raw" / "note.md"
    raw_file.parent.mkdir(parents=True)
    raw_file.write_text("imported", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_id, [str(doc)])

    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    metadata["file_hashes"] = {"note.md": "hash", "uploaded.md": "other-hash"}
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")

    result = manager.unlink_folder("kb", folder_id)

    assert result is not None
    assert result["was_indexed"] is True
    on_disk = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert on_disk["file_hashes"] == {"uploaded.md": "other-hash"}


def test_unlink_of_an_unknown_folder_removes_nothing(tmp_path: Path) -> None:
    manager, _metadata_file, _folder_id, _doc = _manager_with_linked_folder(tmp_path)

    assert manager.unlink_folder("kb", "no-such-id") is None
    assert manager.get_linked_folders("kb") != []


def test_unlink_drops_the_empty_folders_the_linked_folder_left_behind(tmp_path: Path) -> None:
    """A folder shell without any document is noise, not a document.

    The linked folder contributed the ``sub/`` tree under ``raw/``; deleting its
    documents but keeping the directory would show the user a folder that holds
    nothing at all.
    """
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    (source / "sub").mkdir(parents=True)
    doc = source / "sub" / "note.md"
    doc.write_text("hello", encoding="utf-8")
    folder_info = manager.link_folder("kb", str(source))

    staged = kb_dir / "raw" / "sub" / "note.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("imported", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_info["id"], [str(doc)])

    result = manager.unlink_folder("kb", folder_info["id"])

    assert result is not None
    assert not staged.parent.exists()
    assert (kb_dir / "raw").is_dir()


def test_unlink_keeps_a_folder_that_still_holds_a_document(tmp_path: Path) -> None:
    """Only the emptied directories may go — the rest is the user's own layout."""
    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    kb_dir = manager.base_dir / "kb"
    kb_dir.mkdir()
    manager.register_knowledge_base("kb")

    source = tmp_path / "notes"
    (source / "sub").mkdir(parents=True)
    doc = source / "sub" / "note.md"
    doc.write_text("hello", encoding="utf-8")
    folder_info = manager.link_folder("kb", str(source))

    staged = kb_dir / "raw" / "sub" / "note.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("imported", encoding="utf-8")
    kept = staged.parent / "kept.md"
    kept.write_text("uploaded", encoding="utf-8")
    manager.update_folder_sync_state("kb", folder_info["id"], [str(doc)])

    result = manager.unlink_folder("kb", folder_info["id"])

    assert result is not None
    assert not staged.exists()
    assert kept.read_text(encoding="utf-8") == "uploaded"
    assert staged.parent.is_dir()
