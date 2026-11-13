"""Document-scoped retrieval must stay inside one document — and keep its figures.

A knowledge base holds several papers that answer the same question, so a
whole-KB search cannot say which file a passage came from. Scoping the corpus
to one document is what makes a citation trustworthy; it must also keep that
document's figures, because for a scanned exam paper the figure node is where
the question's diagram lives.
"""

from __future__ import annotations

from pathlib import Path

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
import pytest

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module


def _node(node_id: str, text: str, **metadata: object) -> TextNode:
    node = TextNode(text=text, id_=node_id, metadata=metadata)
    node.embedding = [0.1] * 8
    return node


@pytest.fixture
def scoped_index(tmp_path: Path) -> tuple[VectorStoreIndex, Path]:
    raw = tmp_path / "raw"
    (raw / "papers").mkdir(parents=True)
    exam = raw / "papers" / "exam.pdf"
    other = raw / "papers" / "other.pdf"
    exam.write_bytes(b"%PDF-1.4 exam")
    other.write_bytes(b"%PDF-1.4 other")
    nodes = [
        _node(
            "exam-text",
            "Kanas lake sits in the Altai mountains.",
            document_key="papers/exam.pdf",
            file_path=str(exam),
            page_status="searchable",
        ),
        _node(
            "exam-visual",
            "[Source visual] exam.pdf: Figure 2",
            content_type="source_visual",
            file_path=str(exam),
            file_name="exam.pdf",
            caption="Figure 2",
            visual_asset_id="asset-1",
        ),
        _node(
            "exam-ocr",
            "A page that still needs OCR.",
            document_key="papers/exam.pdf",
            file_path=str(exam),
            page_status="needs_ocr",
        ),
        _node(
            "other-text",
            "Kanas lake sits in the Altai mountains too.",
            document_key="papers/other.pdf",
            file_path=str(other),
            page_status="searchable",
        ),
    ]
    return VectorStoreIndex(nodes, embed_model=MockEmbedding(embed_dim=8)), raw


def test_scoped_retrieval_keeps_the_documents_figures(scoped_index) -> None:
    index, raw = scoped_index

    hits = retriever_module.retrieve_scoped_nodes(
        index, "Kanas lake", ["papers/exam.pdf"], top_k=10, raw_root=str(raw)
    )

    ids = {hit.node.node_id for hit in hits}
    assert "exam-text" in ids
    assert "exam-visual" in ids
    assert "exam-ocr" not in ids
    assert "other-text" not in ids


def test_scoped_retrieval_never_crosses_into_another_document(scoped_index) -> None:
    index, raw = scoped_index

    hits = retriever_module.retrieve_scoped_nodes(
        index, "Kanas lake", ["papers/other.pdf"], top_k=10, raw_root=str(raw)
    )

    ids = {hit.node.node_id for hit in hits}
    assert ids == {"other-text"}


def test_scoped_retrieval_of_an_unknown_document_returns_nothing(scoped_index) -> None:
    index, raw = scoped_index

    hits = retriever_module.retrieve_scoped_nodes(
        index, "Kanas lake", ["papers/missing.pdf"], top_k=10, raw_root=str(raw)
    )

    assert hits == []


def test_a_figure_only_document_is_reachable_through_its_raw_path(tmp_path: Path) -> None:
    """A document whose only nodes are figures carries no key — the raw path finds it."""
    raw = tmp_path / "raw"
    (raw / "notes").mkdir(parents=True)
    notes = raw / "notes" / "lesson.docx"
    notes.write_bytes(b"PK\x03\x04 lesson")
    node = _node(
        "notes-visual",
        "[Source visual] lesson.docx: Slide 3",
        content_type="source_visual",
        file_path=str(notes),
        file_name="lesson.docx",
        caption="Slide 3",
        visual_asset_id="asset-2",
    )
    index = VectorStoreIndex([node], embed_model=MockEmbedding(embed_dim=8))

    hits = retriever_module.retrieve_scoped_nodes(
        index, "Slide 3", ["notes/lesson.docx"], top_k=5, raw_root=str(raw)
    )

    assert {hit.node.node_id for hit in hits} == {"notes-visual"}
