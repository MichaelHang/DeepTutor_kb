"""A page's blocks must not be cut in half by the chunk window.

MinerU hands over a page as the blocks its layout model found: the question,
its options, the figure caption and the material around them are separate
blocks. Joining the whole page into one text and cutting it at a fixed
window splits a question between its number and its stem, and the retrieval
then finds a passage that ends on "1." with no question under it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.services.rag.source_pages import (
    _page_block_groups,
    _token_estimate,
    build_pdf_documents,
)


def _blocks() -> list[str]:
    return [
        "2025年1月浙江省普通高校招生选考科目考试",
        "选择题部分",
        "碳中和背景下，发展海上风电成为全球共识。完成下面小题。",
        "1. 近年来，我国海上风电装机容量快速增长的主要原因是（）\n"
        "A. 风能清洁    B. 国家政策支持    C. 风能可再生    D. 市场需求增加",
        "2. 海上风电在我国总发电量中占比低，是因为（）\nA. ①③ B. ①④ C. ②③ D. ②④",
        "下图为某地地质剖面图。完成下面小题。",
    ]


def test_a_question_keeps_its_number_its_stem_and_its_options() -> None:
    groups = _page_block_groups(_blocks(), 512)

    whole = [group for group in groups if "1. 近年来" in group]
    assert whole, "the question must not be split across groups"
    question = whole[0]
    stem = question[question.index("1. 近年来") :]
    assert "A. 风能清洁" in stem
    assert "D. 市场需求增加" in stem


def test_no_block_is_cut_in_half() -> None:
    blocks = _blocks()

    groups = _page_block_groups(blocks, 512)
    joined = "\n\n".join(groups)

    for block in blocks:
        assert block in joined


def test_a_group_stays_within_the_window() -> None:
    groups = _page_block_groups(_blocks(), 512)

    assert groups
    for group in groups:
        assert _token_estimate(group) <= 512


def test_a_block_that_does_not_fit_alone_still_stands() -> None:
    long_block = "填" * 2000

    groups = _page_block_groups([long_block, "短句"], 512)

    assert groups[0] == long_block
    assert groups[1] == "短句"


def _parsed(blocks: list[dict[str, Any]]) -> Any:
    class _Parsed:
        markdown = ""
        parser_signature = "sig"
        engine = "mineru"

        def __init__(self, parsed_blocks: list[dict[str, Any]]) -> None:
            self.blocks = parsed_blocks

    return _Parsed(blocks)


def _write_pdf(path: Any, pages: int = 2) -> None:
    import pymupdf

    document = pymupdf.open()
    for _ in range(pages):
        document.new_page()
    document.save(str(path))
    document.close()


def test_a_page_becomes_one_document_per_group(tmp_path) -> None:
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    pdf = raw / "exam.pdf"
    _write_pdf(pdf)
    blocks = [
        {"type": "text", "page_idx": 0, "text": "第一块"},
        {"type": "text", "page_idx": 0, "text": "第二块"},
        {"type": "footer", "page_idx": 0, "text": "试卷第1页"},
    ]

    documents = build_pdf_documents(pdf, _parsed(blocks), kb_dir)

    assert [document.text for document in documents] == [
        "第一块\n\n第二块",
        "[Unsearchable PDF page 2]",
    ]
    assert {document.metadata["page_index"] for document in documents} == {0, 1}
    assert documents[0].metadata["page_status"] == "searchable"
    assert documents[0].metadata["document_key"] == "exam.pdf"
    assert len({document.id_ for document in documents}) == len(documents)


def test_a_page_that_holds_more_than_one_window_becomes_several_documents(tmp_path) -> None:
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    pdf = raw / "exam.pdf"
    _write_pdf(pdf, pages=1)
    blocks = [{"type": "text", "page_idx": 0, "text": f"第{i}块" + "内容" * 60} for i in range(6)]

    documents = build_pdf_documents(pdf, _parsed(blocks), kb_dir)

    assert len(documents) > 1
    assert len({document.id_ for document in documents}) == len(documents)
    assert {document.metadata["page_index"] for document in documents} == {0}
    # No block was cut to make a group fit.
    for block in blocks:
        assert any(block["text"] in document.text for document in documents)


def test_a_page_without_text_is_marked_as_needing_ocr(tmp_path) -> None:
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    pdf = raw / "scan.pdf"
    _write_pdf(pdf, pages=1)

    documents = build_pdf_documents(pdf, _parsed([]), kb_dir)

    assert documents[0].text == "[Unsearchable PDF page 1]"
    assert documents[0].metadata["page_status"] == "needs_ocr"


@pytest.mark.parametrize("budget", [64, 128, 512])
def test_the_groups_do_not_depend_on_how_much_room_is_left(budget: int) -> None:
    blocks = _blocks()

    groups = _page_block_groups(blocks, budget)

    for block in blocks:
        assert any(block in group for group in groups)


def test_the_page_catalog_lists_a_page_once(tmp_path) -> None:
    from deeptutor.services.rag.source_pages import persist_page_catalog

    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    pdf = raw / "exam.pdf"
    _write_pdf(pdf, pages=1)
    blocks = [{"type": "text", "page_idx": 0, "text": f"第{i}块" + "内容" * 60} for i in range(6)]

    documents = build_pdf_documents(pdf, _parsed(blocks), kb_dir)
    assert len(documents) > 1
    storage = tmp_path / "storage"
    storage.mkdir()
    persist_page_catalog(documents, storage)

    catalog = json.loads((storage / "source_pages.json").read_text(encoding="utf-8"))

    assert len(catalog["pages"]) == 1
    assert catalog["pages"][0]["page_index"] == 0


def test_a_block_beyond_the_last_page_is_kept(tmp_path) -> None:
    kb_dir = tmp_path / "kb"
    raw = kb_dir / "raw"
    raw.mkdir(parents=True)
    pdf = raw / "exam.pdf"
    _write_pdf(pdf, pages=1)
    blocks = [
        {"type": "text", "page_idx": 0, "text": "第一页"},
        {"type": "text", "page_idx": 7, "text": "溢出的块"},
    ]

    documents = build_pdf_documents(pdf, _parsed(blocks), kb_dir)

    assert any("溢出的块" in document.text for document in documents)
