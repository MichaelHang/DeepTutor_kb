"""关联文件夹的文档应以硬链接暂存：知识库只留一份字节，并跟随原文件更新。

「关联」意味着知识库看到的就是那个文件夹里的文件，而不是它的一份拷贝。
拷贝既要多占一份磁盘，也会立刻和原文件分家——用户改了讲义，知识库里
那份还是旧的。这几个测试把该语义钉住：同设备时用硬链接，跨设备时退回
拷贝（内容一样，只是无法共享），任何覆盖写都先断开链接，绝不写穿到用户
自己的文件上。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from deeptutor.knowledge.add_documents import DocumentAdder, relink_staged_copy
from deeptutor.knowledge.staging import content_hash, stage_source
from deeptutor.services.file_io import detach_if_hardlinked, is_hardlinked
from deeptutor.services.rag.factory import DEFAULT_PROVIDER, LIGHTRAG_PROVIDER


def _same_file(left: Path, right: Path) -> bool:
    """True when both names are the very same file on disk."""
    left_stat = left.stat()
    right_stat = right.stat()
    return (left_stat.st_dev, left_stat.st_ino) == (right_stat.st_dev, right_stat.st_ino)


def _adder(tmp_path: Path) -> DocumentAdder:
    (tmp_path / "kb").mkdir()
    return DocumentAdder(
        kb_name="kb",
        base_dir=str(tmp_path),
        rag_provider=DEFAULT_PROVIDER,
    )


def test_stage_source_links_the_document_instead_of_copying_it(tmp_path: Path) -> None:
    """硬链接暂存后知识库里那份与原文件是同一个 inode。"""
    source = tmp_path / "notes.md"
    source.write_text("first", encoding="utf-8")
    dest = tmp_path / "raw" / "notes.md"

    staged, copied = stage_source(source, dest, prefer_hardlink=True)

    assert copied is True and staged == dest
    assert _same_file(source, staged)


def test_staged_link_follows_an_in_place_edit_of_the_source(tmp_path: Path) -> None:
    """用户原地改原文件后，知识库里那份自动就是新内容。"""
    source = tmp_path / "notes.md"
    source.write_text("first", encoding="utf-8")
    dest = tmp_path / "raw" / "notes.md"
    staged, _ = stage_source(source, dest, prefer_hardlink=True)

    source.write_text("second", encoding="utf-8")

    assert staged.read_text(encoding="utf-8") == "second"


def test_stage_source_falls_back_to_a_copy_when_the_link_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨设备等场景无法建链接时退回拷贝，内容照样正确。"""
    source = tmp_path / "notes.md"
    source.write_text("content", encoding="utf-8")
    dest = tmp_path / "raw" / "notes.md"

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", refuse)

    staged, copied = stage_source(source, dest, prefer_hardlink=True)

    assert copied is True and staged == dest
    assert staged.read_text(encoding="utf-8") == "content"
    assert not _same_file(source, staged)


def test_stage_source_copies_when_hard_links_are_not_requested(tmp_path: Path) -> None:
    """未要求硬链接时保持原来的拷贝语义。"""
    source = tmp_path / "notes.md"
    source.write_text("content", encoding="utf-8")
    dest = tmp_path / "raw" / "notes.md"

    staged, copied = stage_source(source, dest)

    assert copied is True and staged == dest
    assert not _same_file(source, staged)


def test_linked_folder_sync_stages_hard_links(tmp_path: Path) -> None:
    """关联文件夹里的文档被硬链接进 raw/，路径保留相对结构。"""
    folder = tmp_path / "资料"
    (folder / "第一讲").mkdir(parents=True)
    source = folder / "第一讲" / "讲义.docx"
    source.write_bytes(b"doc bytes")

    adder = _adder(tmp_path)
    staged = adder.add_documents([str(source)], source_root=folder)

    assert len(staged) == 1
    assert staged[0] == adder.raw_dir / "第一讲" / "讲义.docx"
    assert _same_file(source, staged[0])


def test_sources_outside_the_linked_root_are_copied(tmp_path: Path) -> None:
    """不属于关联文件夹的来源不占用那个路径，仍按原样拷贝。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    elsewhere = tmp_path / "elsewhere.docx"
    elsewhere.write_bytes(b"other bytes")

    adder = _adder(tmp_path)
    staged = adder.add_documents([str(elsewhere)], source_root=folder)

    assert len(staged) == 1
    assert staged[0] == adder.raw_dir / "elsewhere.docx"
    assert not _same_file(elsewhere, staged[0])


def test_detaching_a_hard_link_keeps_the_original_intact(tmp_path: Path) -> None:
    """断开链接后再写，只改知识库那份，用户原文件不受影响。"""
    source = tmp_path / "notes.md"
    source.write_text("original", encoding="utf-8")
    dest = tmp_path / "raw" / "notes.md"
    stage_source(source, dest, prefer_hardlink=True)

    assert detach_if_hardlinked(dest) is True
    dest.write_text("replaced", encoding="utf-8")

    assert source.read_text(encoding="utf-8") == "original"
    assert dest.read_text(encoding="utf-8") == "replaced"


def test_detaching_leaves_an_ordinary_file_alone(tmp_path: Path) -> None:
    """普通文件不该被当成链接删掉。"""
    dest = tmp_path / "notes.md"
    dest.write_text("keep", encoding="utf-8")

    assert is_hardlinked(dest) is False
    assert detach_if_hardlinked(dest) is False
    assert dest.read_text(encoding="utf-8") == "keep"


def _legacy_kb(tmp_path: Path, source: Path) -> tuple[DocumentAdder, Path]:
    """A KB holding the old copy of *source*, with its index record in place."""
    adder = _adder(tmp_path)
    staged = adder.raw_dir / source.name
    staged.write_bytes(source.read_bytes())
    metadata = {"file_hashes": {source.name: content_hash(source)}}
    (tmp_path / "kb" / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    return adder, staged


def test_resync_turns_an_old_copy_into_a_link(tmp_path: Path) -> None:
    """重新同步时，已索引的旧拷贝换成硬链接，且不必重新索引。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.docx"
    source.write_bytes(b"doc bytes")
    adder, staged = _legacy_kb(tmp_path, source)
    assert not _same_file(source, staged)

    processed = adder.add_documents([str(source)], source_root=folder)

    assert processed == []
    assert _same_file(source, staged)
    assert staged.read_bytes() == b"doc bytes"


def test_relink_leaves_an_existing_link_alone(tmp_path: Path) -> None:
    """已经是硬链接的文件不需要再处理。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.docx"
    source.write_bytes(b"doc bytes")
    adder = _adder(tmp_path)
    staged = adder.raw_dir / source.name
    stage_source(source, staged, prefer_hardlink=True)

    assert relink_staged_copy(source, adder.raw_dir, folder) is False
    assert _same_file(source, staged)


def test_relink_keeps_the_copy_when_the_link_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨设备无法建链接时保留原拷贝，不把文件弄丢。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.docx"
    source.write_bytes(b"doc bytes")
    adder, staged = _legacy_kb(tmp_path, source)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise OSError(18, "Invalid cross-device link")

    monkeypatch.setattr(os, "link", refuse)

    assert relink_staged_copy(source, adder.raw_dir, folder) is False
    assert staged.exists()
    assert staged.read_bytes() == b"doc bytes"
    assert not _same_file(source, staged)


def test_lightrag_documents_stay_ordinary_copies(tmp_path: Path) -> None:
    """LightRAG 拒绝共享 inode 的源文件，它的文档必须保持普通拷贝。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.docx"
    source.write_bytes(b"doc bytes")

    (tmp_path / "kb").mkdir()
    adder = DocumentAdder(
        kb_name="kb",
        base_dir=str(tmp_path),
        rag_provider=LIGHTRAG_PROVIDER,
        accepted_indexing_snapshot=object(),
    )
    staged = adder.add_documents([str(source)], source_root=folder)

    assert len(staged) == 1
    assert not _same_file(source, staged[0])
    assert staged[0].read_bytes() == b"doc bytes"


def _write_linked_state(tmp_path: Path, folder: Path, inodes: dict[str, int]) -> None:
    """Record a linked folder's sync state the way the sync route does."""
    metadata = {
        "file_hashes": {},
        "linked_folders": [
            {"id": "f1", "path": str(folder), "synced_inodes": inodes},
        ],
    }
    (tmp_path / "kb" / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")


def test_replaced_source_takes_the_place_of_the_old_version(tmp_path: Path) -> None:
    """编辑器另存替换了源文件时，新版本顶替旧版本，不并列留下两份。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.md"
    source.write_text("第一版", encoding="utf-8")

    adder = _adder(tmp_path)
    staged = adder.raw_dir / "讲义.md"
    stage_source(source, staged, prefer_hardlink=True)
    original_inode = source.stat().st_ino

    # 编辑器的保存方式：写临时文件，再改名覆盖原文件
    replacement = folder / "讲义.md.tmp"
    replacement.write_text("第二版", encoding="utf-8")
    replacement.replace(source)
    assert source.stat().st_ino != original_inode

    _write_linked_state(tmp_path, folder, {str(source): original_inode})

    processed = adder.add_documents([str(source)], source_root=folder)

    assert processed == [staged]
    assert staged.read_text(encoding="utf-8") == "第二版"
    assert _same_file(source, staged)
    assert not (adder.raw_dir / "讲义 (2).md").exists()


def test_an_edit_in_place_keeps_a_single_staged_copy(tmp_path: Path) -> None:
    """源文件被原地改写时，知识库里那份跟着变，且不产生副本。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.md"
    source.write_text("第一版", encoding="utf-8")

    adder = _adder(tmp_path)
    staged = adder.raw_dir / "讲义.md"
    stage_source(source, staged, prefer_hardlink=True)
    original_inode = source.stat().st_ino

    source.write_text("第二版", encoding="utf-8")

    _write_linked_state(tmp_path, folder, {str(source): original_inode})

    adder.add_documents([str(source)], source_root=folder)

    assert staged.read_text(encoding="utf-8") == "第二版"
    assert not (adder.raw_dir / "讲义 (2).md").exists()


def test_a_file_uploaded_under_the_same_name_is_kept(tmp_path: Path) -> None:
    """用户上传的同名文件不该被同步悄悄顶掉，原有规则保留两份。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.md"
    source.write_text("原讲义", encoding="utf-8")

    adder = _adder(tmp_path)
    staged = adder.raw_dir / "讲义.md"
    staged.write_text("用户上传的内容", encoding="utf-8")
    original_inode = source.stat().st_ino

    _write_linked_state(tmp_path, folder, {str(source): original_inode})

    processed = adder.add_documents([str(source)], source_root=folder)

    assert len(processed) == 1
    assert staged.read_text(encoding="utf-8") == "用户上传的内容"
    assert (adder.raw_dir / "讲义 (2).md").read_text(encoding="utf-8") == "原讲义"


def test_an_uploaded_file_survives_a_replaced_source(tmp_path: Path) -> None:
    """源文件被替换时，用户自己上传的同名内容也不能被删掉。"""
    folder = tmp_path / "资料"
    folder.mkdir()
    source = folder / "讲义.md"
    source.write_text("原讲义", encoding="utf-8")

    adder = _adder(tmp_path)
    staged = adder.raw_dir / "讲义.md"
    stage_source(source, staged, prefer_hardlink=True)
    original_inode = source.stat().st_ino

    # 用户上传了同名文件：raw/ 里那份变成用户自己的内容
    staged.unlink()
    staged.write_text("用户上传的内容", encoding="utf-8")

    replacement = folder / "讲义.md.tmp"
    replacement.write_text("第二版", encoding="utf-8")
    replacement.replace(source)

    _write_linked_state(tmp_path, folder, {str(source): original_inode})

    adder.add_documents([str(source)], source_root=folder)

    assert staged.read_text(encoding="utf-8") == "用户上传的内容"
    assert (adder.raw_dir / "讲义 (2).md").read_text(encoding="utf-8") == "第二版"
