"""Tests for dropping removed documents out of a published LlamaIndex index.

A removal must not embed anything again: the vectors of the documents that
stay are carried over as they are. That only works when the mapping from a
vector position to its node survives the removal, so these tests check the
mapping as well as the visible outcome of a retrieval.
"""

from __future__ import annotations

from pathlib import Path

from llama_index.core import Settings, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import TextNode
import numpy as np
import pytest

from deeptutor.services.rag.pipelines.llamaindex import storage as storage_module
from deeptutor.services.rag.pipelines.llamaindex import vector_store
from deeptutor.services.rag.pipelines.llamaindex.config import VectorIndexConfig

faiss = pytest.importorskip("faiss")
pytest.importorskip("llama_index.vector_stores.faiss")

_DIM = 8
_VECTORS = {
    "alpha": [1, 0, 0, 0, 0, 0, 0, 0],
    "beta": [0, 1, 0, 0, 0, 0, 0, 0],
    "gamma": [0.9, 0.1, 0, 0, 0, 0, 0, 0],
    "delta": [0, 0, 1, 0, 0, 0, 0, 0],
}
# A query token that is not a substring of any node token, so the fake
# embedding of the query is the vector of exactly one node.
_PROBE = "probe"

# How many times the fake embedding model was asked for a vector.
_CALLS: dict[str, int] = {"count": 0}


class _FakeEmbed(BaseEmbedding):
    """Deterministic embedding keyed by a substring of the text."""

    def _vec(self, text: str) -> list[float]:
        _CALLS["count"] += 1
        for key, vector in _VECTORS.items():
            if key in text:
                return [float(x) for x in vector]
        return [0.0] * _DIM

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._vec(text)

    def _get_query_embedding(self, text: str) -> list[float]:
        return self._vec(text)

    async def _aget_query_embedding(self, text: str) -> list[float]:
        return self._vec(text)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._vec(text)


@pytest.fixture(autouse=True)
def _fake_embed_model() -> None:
    _CALLS["count"] = 0
    Settings.embed_model = _FakeEmbed()
    storage_module.clear_index_cache()
    yield
    storage_module.clear_index_cache()


def _build_kb(
    tmp_path: Path,
    documents: list[tuple[str, str]],
    *,
    index_config: VectorIndexConfig | None = None,
) -> tuple[Path, Path]:
    """A knowledge base with one version, indexed as FAISS."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    nodes = []
    for key, vector_key in documents:
        path = raw_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(key, encoding="utf-8")
        node = TextNode(text=f"node {key}", id_=f"node-{key}")
        node.embedding = [float(x) for x in _VECTORS[vector_key]]
        node.metadata = {"file_name": Path(key).name, "file_path": str(path)}
        nodes.append(node)
    storage_dir = kb_dir / "version-1"
    context = vector_store.new_faiss_storage_context(_DIM, index_config)
    assert context is not None
    VectorStoreIndex(nodes=nodes, storage_context=context)
    context.persist(persist_dir=str(storage_dir))
    return kb_dir, storage_dir


def _vectors_by_node(storage_dir: Path) -> dict[str, list[float]]:
    """The stored vector of every node, read back through the index structure."""
    index = vector_store.load_index(storage_dir)
    faiss_index = index.vector_store._faiss_index
    return {
        node_id: faiss_index.reconstruct(int(vector_id)).tolist()
        for vector_id, node_id in index.index_struct.nodes_dict.items()
    }


def test_prune_drops_the_nodes_of_the_removed_document(tmp_path: Path) -> None:
    """The nodes of a removed document leave the index."""
    _kb_dir, existing = _build_kb(
        tmp_path, [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma")]
    )
    target = tmp_path / "kb" / "version-2"

    result = storage_module.insert_documents_pruned(existing, target, [], {"beta.md"})

    assert result.removed_documents == 1
    assert result.removed_nodes == 1
    assert result.added_documents == 0
    index = vector_store.load_index(target)
    assert set(index.docstore.docs) == {"node-alpha.md", "node-gamma.md"}


def test_prune_embeds_nothing(tmp_path: Path) -> None:
    """A removal costs no embedding at all."""
    _kb_dir, existing = _build_kb(
        tmp_path, [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma")]
    )
    target = tmp_path / "kb" / "version-2"

    storage_module.insert_documents_pruned(existing, target, [], {"beta.md"})

    assert _CALLS["count"] == 0


def test_prune_keeps_the_vectors_of_the_surviving_documents(tmp_path: Path) -> None:
    """The vectors that stay are carried over, not embedded again."""
    _kb_dir, existing = _build_kb(
        tmp_path, [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma")]
    )
    before = _vectors_by_node(existing)
    target = tmp_path / "kb" / "version-2"

    storage_module.insert_documents_pruned(existing, target, [], {"beta.md"})

    after = _vectors_by_node(target)
    assert set(after) == {"node-alpha.md", "node-gamma.md"}
    assert after["node-alpha.md"] == before["node-alpha.md"]
    assert after["node-gamma.md"] == before["node-gamma.md"]


def test_prune_keeps_the_retrieval_pointing_at_the_right_nodes(tmp_path: Path) -> None:
    """Removing a node must not shift the vectors of the nodes behind it.

    The vector backends answer a query with a position, and the index turns
    that position into a node through its index structure. A wrong mapping
    would answer with a neighbouring document instead of failing.
    """
    _kb_dir, existing = _build_kb(
        tmp_path,
        [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma"), ("delta.md", "delta")],
    )
    target = tmp_path / "kb" / "version-2"

    storage_module.insert_documents_pruned(existing, target, [], {"beta.md"})

    index = vector_store.load_index(target)
    hits = index.as_retriever(similarity_top_k=4).retrieve("gamma")
    assert [hit.node.node_id for hit in hits][0] == "node-gamma.md"
    assert "node-beta.md" not in {hit.node.node_id for hit in hits}


def test_prune_of_a_nested_document_matches_its_path(tmp_path: Path) -> None:
    """A document in a subdirectory of ``raw`` is matched by its relative key."""
    kb_dir, existing = _build_kb(tmp_path, [("notes/alpha.md", "alpha"), ("notes/beta.md", "beta")])
    target = kb_dir / "version-2"

    result = storage_module.insert_documents_pruned(existing, target, [], {"notes/alpha.md"})

    assert result.removed_nodes == 1
    index = vector_store.load_index(target)
    assert set(index.docstore.docs) == {"node-notes/beta.md"}


def test_prune_of_an_unknown_document_changes_nothing(tmp_path: Path) -> None:
    """A document that was never indexed leaves the index as it is."""
    _kb_dir, existing = _build_kb(tmp_path, [("alpha.md", "alpha"), ("beta.md", "beta")])
    target = tmp_path / "kb" / "version-2"

    result = storage_module.insert_documents_pruned(existing, target, [], {"ghost.md"})

    assert result.removed_nodes == 0
    index = vector_store.load_index(target)
    assert set(index.docstore.docs) == {"node-alpha.md", "node-beta.md"}


def test_prune_of_an_hnsw_index_keeps_the_retrieval_intact(tmp_path: Path) -> None:
    """HNSW cannot drop rows in place, so it is rebuilt from the vectors."""
    _kb_dir, existing = _build_kb(
        tmp_path,
        [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma")],
        index_config=VectorIndexConfig(type="hnsw", hnsw_m=8, hnsw_ef_construction=32),
    )
    target = tmp_path / "kb" / "version-2"

    storage_module.insert_documents_pruned(existing, target, [], {"beta.md"})

    index = vector_store.load_index(target)
    assert type(index.vector_store._faiss_index).__name__ == "IndexHNSWFlat"
    hits = index.as_retriever(similarity_top_k=3).retrieve("gamma")
    assert [hit.node.node_id for hit in hits][0] == "node-gamma.md"


def test_prune_of_a_simple_index_drops_the_vectors(tmp_path: Path) -> None:
    """A legacy SimpleVectorStore index loses the vectors of the removed nodes."""
    kb_dir = tmp_path / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    nodes = []
    for key, vector_key in (("alpha.md", "alpha"), ("beta.md", "beta")):
        path = raw_dir / key
        path.write_text(key, encoding="utf-8")
        node = TextNode(text=f"node {key}", id_=f"node-{key}")
        node.embedding = [float(x) for x in _VECTORS[vector_key]]
        node.metadata = {"file_name": key, "file_path": str(path)}
        nodes.append(node)
    existing = kb_dir / "version-1"
    VectorStoreIndex(nodes=nodes).storage_context.persist(persist_dir=str(existing))
    target = kb_dir / "version-2"

    result = storage_module.insert_documents_pruned(existing, target, [], {"alpha.md"})

    assert result.removed_nodes == 1
    index = vector_store.load_index(target)
    assert set(index.docstore.docs) == {"node-beta.md"}
    hits = index.as_retriever(similarity_top_k=2).retrieve("beta")
    assert [hit.node.node_id for hit in hits][0] == "node-beta.md"


def test_prune_then_add_embeds_only_the_new_document(tmp_path: Path) -> None:
    """A new document joins the pruned snapshot and is embedded on its own."""
    _kb_dir, existing = _build_kb(
        tmp_path, [("alpha.md", "alpha"), ("beta.md", "beta"), ("gamma.md", "gamma")]
    )
    target = tmp_path / "kb" / "version-2"
    embed = Settings.embed_model

    new_node = TextNode(text="node delta", id_="node-delta")
    new_node.embedding = [float(x) for x in _VECTORS["delta"]]
    new_node.metadata = {
        "file_name": "delta.md",
        "file_path": str(tmp_path / "kb" / "raw" / "delta.md"),
    }

    result = storage_module.insert_documents_pruned(existing, target, [new_node], {"beta.md"})

    assert result.removed_nodes == 1
    assert result.added_documents == 1
    index = vector_store.load_index(target)
    assert set(index.docstore.docs) == {"node-alpha.md", "node-gamma.md", "node-delta"}
    # The stored vector of the new document is the one it was given.
    vectors = _vectors_by_node(target)
    assert np.allclose(vectors["node-delta"], _VECTORS["delta"])
