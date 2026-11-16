"""A source-visual record must not crowd out the passage that holds the text.

A visual record is indexed as ``[Source visual] exam.pdf: Source figure`` — the
file name and a placeholder caption. Any query that names the file therefore
matches every visual record of that file, and the passages that carry the
actual text drop out of the top-k. The answer then gets built from
placeholders: "Source figure" is not a finding.
"""

from __future__ import annotations

from typing import Any

from llama_index.core import VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import NodeWithScore, TextNode
import pytest

from deeptutor.services.rag.pipelines.llamaindex import retrievers as retriever_module
from deeptutor.services.rag.pipelines.llamaindex.config import RetrievalConfig


def _hit(node_id: str, visual: bool) -> NodeWithScore:
    metadata = {"content_type": "source_visual"} if visual else {}
    node = TextNode(text=f"content of {node_id}", id_=node_id, metadata=metadata)
    return NodeWithScore(node=node, score=1.0)


def test_the_visual_records_cannot_take_every_slot() -> None:
    hits = [_hit(f"v{i}", True) for i in range(6)] + [_hit(f"t{i}", False) for i in range(6)]

    kept = retriever_module._text_first(hits, 5)

    visual = sum(1 for hit in kept if retriever_module._is_visual_hit(hit))
    assert visual == 2
    assert len(kept) == 5


def test_visual_records_stay_within_their_share() -> None:
    hits = [_hit(f"v{i}", True) for i in range(20)] + [_hit(f"t{i}", False) for i in range(6)]

    kept = retriever_module._text_first(hits, 5)

    visual = sum(1 for hit in kept if retriever_module._is_visual_hit(hit))
    assert visual == 2
    assert len(kept) == 5


def test_fewer_hits_than_the_limit_are_kept_as_they_are() -> None:
    hits = [_hit("v0", True), _hit("v1", True)]

    assert retriever_module._text_first(hits, 5) == hits


def test_the_text_fills_the_slots_the_visual_records_leave() -> None:
    hits = [_hit("t0", False), _hit("v0", True)]

    kept = retriever_module._text_first(hits, 5)

    assert [hit.node.node_id for hit in kept] == ["t0", "v0"]


def test_a_scoped_query_drops_the_document_name_it_repeats() -> None:
    query = "2025年浙江6月高考地理真题 第1题 冷湖 考查什么"

    stripped = retriever_module._without_scoped_document_names(
        query, ["2025年浙江6月高考地理真题.pdf"]
    )

    assert "2025年浙江6月高考地理真题" not in stripped
    assert "冷湖" in stripped


def test_a_query_that_is_only_the_document_name_is_kept() -> None:
    query = "2025年浙江6月高考地理真题.pdf"

    stripped = retriever_module._without_scoped_document_names(
        query, ["2025年浙江6月高考地理真题.pdf"]
    )

    assert stripped == query


def test_a_name_that_is_not_in_the_query_is_left_alone() -> None:
    query = "洛川塬 考察区"

    stripped = retriever_module._without_scoped_document_names(
        query, ["2026年6月高考浙江卷地理高考真题（网络 收集版）.pdf"]
    )

    assert stripped == query


def _scoped_index() -> VectorStoreIndex:
    """A document whose figures outnumber its passages, as a scanned exam does."""

    def node(node_id: str, text: str, **metadata: Any) -> TextNode:
        item = TextNode(text=text, id_=node_id, metadata=metadata)
        item.embedding = [0.1] * 8
        return item

    nodes = [
        node(
            f"v{i}",
            f"[Source visual] exam.pdf: Source figure\nContext: {i}",
            content_type="source_visual",
            file_path="/kb/raw/exam.pdf",
            file_name="exam.pdf",
        )
        for i in range(8)
    ]
    nodes += [
        node(
            f"t{i}",
            f"1. 冷湖的重新兴起得益于（ ） A. 盐类资源丰富 B. 自然环境独特 C. 文化底蕴深厚 D. 人口大量集聚 {i}",
            document_key="exam.pdf",
            file_path="/kb/raw/exam.pdf",
            page_status="searchable",
        )
        for i in range(3)
    ]
    return VectorStoreIndex(nodes, embed_model=MockEmbedding(embed_dim=8))


def test_a_pool_taken_over_by_visual_records_is_asked_again_wider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    widths: list[int] = []

    def _fake_build(_index, _storage_dir, *, top_k: int, config):
        widths.append(top_k)
        width = top_k

        class _Retriever:
            def retrieve(self, query: str) -> list[NodeWithScore]:
                return [_hit(f"v{i}", True) for i in range(width)]

        return _Retriever()

    monkeypatch.setattr(retriever_module, "build_retriever", _fake_build)
    monkeypatch.setattr(
        retriever_module,
        "retrieval_config_from_settings",
        lambda: RetrievalConfig(profile="vector"),
    )

    kept = retriever_module.retrieve_nodes(object(), tmp_path, "probe", top_k=5)

    assert widths == [10, 40]
    assert len(kept) == 5


def test_a_pool_with_enough_passages_is_not_asked_again_wider() -> None:
    hits = [_hit(f"v{i}", True) for i in range(4)] + [_hit(f"t{i}", False) for i in range(6)]

    assert retriever_module._visual_records_dominate(hits, 5) is False


def test_a_scoped_search_keeps_the_passages_a_query_that_names_the_file_would_lose() -> None:
    index = _scoped_index()

    hits = retriever_module.retrieve_scoped_nodes(
        index,
        "exam.pdf 冷湖的重新兴起得益于",
        ["exam.pdf"],
        top_k=5,
        raw_root="/kb/raw",
    )

    kept = [hit.node.node_id for hit in hits]
    assert len(kept) == 5
    passages = [node_id for node_id in kept if node_id.startswith("t")]
    assert len(passages) >= 3
    visual = [node_id for node_id in kept if node_id.startswith("v")]
    assert len(visual) <= 2
