"""Page-bound PDF evidence shared by indexing, tutoring and authorized previews."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote, urlencode

from pydantic import BaseModel, ConfigDict, Field

SOURCE_SCHEMA_VERSION = 1
CATALOG_FILENAME = "source_pages.json"
# MinerU content_list mixes body text with page chrome. These are the layout
# helpers already dropped before LightRAG indexing and exercise lookup.
# Margin notes (aside_text) and page footnotes stay, because they carry text.
_PAGE_FURNITURE_TYPES = frozenset({"header", "footer", "page_header", "page_footer", "page_number"})


class SourcePageError(ValueError):
    """A safe, user-facing source resolution failure."""


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kb_ref: str
    document_key: str
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_index: int = Field(ge=0)
    page_label: str = ""
    parser_signature: str = ""
    node_id: str = ""
    crop: tuple[float, float, float, float] | None = None


def source_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_source(ref: SourceRef) -> Path:
    from deeptutor.multi_user.knowledge_access import resolve_kb_document_path

    path = resolve_kb_document_path(ref.kb_ref, ref.document_key)
    if path is None or path.suffix.lower() != ".pdf":
        raise SourcePageError("The selected PDF is unavailable or access was revoked.")
    if source_digest(path) != ref.source_digest:
        raise SourcePageError(
            "The source document has changed. Refresh its index before continuing."
        )
    return path


def render_source_page(ref: SourceRef) -> bytes:
    from deeptutor.multi_user.knowledge_access import resolve_for_rag
    from deeptutor.services.rag.source_visuals import page_image

    # Authorize through the same source resolver as existing lesson snapshots.
    resolve_source(ref)
    resource = resolve_for_rag(ref.kb_ref)
    if resource is None:
        raise SourcePageError("The selected PDF is unavailable or access was revoked.")
    try:
        _, pixels = page_image(
            Path(resource.base_dir) / resource.name,
            ref.document_key,
            ref.page_index + 1,
            expected_hash=ref.source_digest,
            region=list(ref.crop) if ref.crop else None,
        )
        return pixels
    except (OSError, ValueError) as exc:
        raise SourcePageError(str(exc)) from exc


def preview_url(ref: SourceRef) -> str:
    query = {
        "source_path": ref.document_key,
        "source_hash": ref.source_digest,
        "page": str(ref.page_index + 1),
    }
    if ref.crop:
        query["region"] = ",".join(str(v) for v in ref.crop)
    return f"/api/knowledge-bases/{quote(ref.kb_ref, safe='')}/source-page?{urlencode(query)}"


def public_source(ref: SourceRef) -> dict[str, Any]:
    return {
        "type": "rag",
        "kb_name": ref.kb_ref,
        "title": f"{ref.document_key} · PDF page {ref.page_index + 1}",
        "source": ref.document_key,
        "page": ref.page_index + 1,
        "url": (
            f"/api/knowledge-bases/{quote(ref.kb_ref, safe='')}/files/"
            f"{quote(ref.document_key, safe='/')}#page={ref.page_index + 1}"
        ),
        "preview_url": preview_url(ref),
        "source_ref": ref.model_dump(),
    }


def _is_page_furniture(block: dict[str, Any]) -> bool:
    """True for MinerU page-chrome blocks that must not become chunks."""
    return str(block.get("type") or "").strip().lower() in _PAGE_FURNITURE_TYPES


def _list_item_pieces(value: Any) -> list[str]:
    """Flatten MinerU ``list_items`` strings.

    Reference lists are ``type="list"`` blocks, with ``sub_type="ref_text"`` for
    a bibliography. Entries are an array of strings; other shapes are ignored
    so a nested object is not indexed as its Python repr.
    """
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        pieces: list[str] = []
        for item in value:
            pieces.extend(_list_item_pieces(item))
        return pieces
    return []


def _block_text(block: dict[str, Any]) -> str:
    """Readable text of one content_list block, including list entries."""
    pieces = [str(block.get(k) or "") for k in ("text", "content", "table_body")]
    for name in ("image_caption", "table_caption", "table_footnote"):
        value = block.get(name) or []
        if isinstance(value, list):
            pieces.extend(str(v) for v in value)
        else:
            pieces.append(str(value))
    pieces.extend(_list_item_pieces(block.get("list_items")))
    return "\n".join(piece for piece in pieces if piece.strip())


def _token_estimate(text: str) -> float:
    """A rough token count: a CJK character is about one token, ASCII about four.

    The chunk window is counted in tokens, so the blocks have to be weighed
    in the same unit before they are grouped.
    """
    ascii_chars = sum(1 for char in text if char.isascii())
    return (len(text) - ascii_chars) + ascii_chars / 4


def _page_block_groups(blocks: list[str], token_budget: int) -> list[str]:
    """Group a page's blocks so that a question is not cut in half.

    MinerU hands over a page as the blocks its layout model found: the
    question, its options, the figure caption and the material around them
    are separate blocks. Joining the whole page into one text and cutting it
    at a fixed window splits a question between its number and its stem — a
    scanned exam page holds more text than one window, so the cut lands
    inside a question every time, and the retrieval then finds a passage
    that ends on "1." with no question under it. The window is applied to
    the groups instead, so it lands between blocks and a question stays
    whole.
    """
    groups: list[str] = []
    current: list[str] = []
    for text in blocks:
        candidate = "\n\n".join([*current, text])
        if current and _token_estimate(candidate) > token_budget:
            groups.append("\n\n".join(current))
            current = [text]
        else:
            current.append(text)
    if current:
        groups.append("\n\n".join(current))
    return groups


def build_pdf_documents(path: Path, parsed: Any, kb_dir: Path) -> list[Any]:
    """Prefer located IR; native PDF pages provide physical locators otherwise.

    MinerU bibliographies are ``list`` blocks whose entries live in
    ``list_items``. Page numbers, running headers, and footers are left out so
    they are not embedded as their own chunks.
    """
    from llama_index.core import Document
    import pymupdf

    from deeptutor.services.rag.pipelines.llamaindex.config import chunk_geometry

    resolved = path.resolve()
    raw = (kb_dir / "raw").resolve()
    if not resolved.is_relative_to(raw):
        return []
    key = resolved.relative_to(raw).as_posix()
    digest = source_digest(path)
    grouped: dict[int, list[str]] = {}
    furniture_pages: set[int] = set()
    content_pages: set[int] = set()
    unlocated: list[str] = []
    for block in parsed.blocks or []:
        if not isinstance(block, dict):
            continue
        index = block.get("page_idx", block.get("page_index"))
        on_page = type(index) is int and index >= 0
        if _is_page_furniture(block):
            if on_page:
                furniture_pages.add(index)
            continue
        text = _block_text(block)
        if on_page:
            content_pages.add(index)
            grouped.setdefault(index, []).append(text)
        elif text:
            unlocated.append(text)
    documents = []
    chunk_size, _ = chunk_geometry()
    page_count = 0
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise SourcePageError("Password protected PDFs cannot supply teaching evidence.")
        page_count = pdf.page_count
        for index, page in enumerate(pdf):
            page_blocks = grouped.get(index, [])
            located = "\n\n".join(page_blocks)
            # Furniture-only pages must not fall back to the text layer, or the
            # printed page number is indexed after its block was dropped.
            # Pages with other blocks keep the previous native-text fallback.
            if located.strip():
                texts = _page_block_groups(page_blocks, chunk_size)
            elif index in furniture_pages and index not in content_pages:
                texts = [""]
            else:
                texts = [page.get_text(sort=True).strip()]
            metadata = {
                "file_name": path.name,
                "file_path": str(path),
                "document_key": key,
                "source_digest": digest,
                "source_schema_version": SOURCE_SCHEMA_VERSION,
                "page_index": index,
                "page": index + 1,
                "page_label": page.get_label() or "",
                "page_count": pdf.page_count,
                "parser_signature": parsed.parser_signature,
                "parse_engine": parsed.engine if located.strip() else "native_pdf",
                "page_status": "searchable"
                if located.strip() or any(text.strip() for text in texts)
                else "needs_ocr",
                "visual_status": "present"
                if page.get_images() or page.get_drawings()
                else "unknown",
            }
            for group_index, text in enumerate(texts):
                documents.append(
                    Document(
                        id_=f"pdf-{digest}-{index}-{group_index}",
                        text=text or f"[Unsearchable PDF page {index + 1}]",
                        metadata=dict(metadata),
                        excluded_embed_metadata_keys=list(metadata),
                        excluded_llm_metadata_keys=["file_path"],
                    )
                )
    for index in grouped:
        # Blocks the parser placed beyond the last page belong to no page, so
        # they are kept as one extra document instead of being dropped.
        if index >= page_count:
            unlocated.extend(grouped[index])
    if unlocated or (not grouped and parsed.engine not in {"text_only", "native_pdf"}):
        extra = "\n\n".join(unlocated) or parsed.markdown.strip()
        if extra:
            documents.append(
                Document(
                    text=extra,
                    metadata={
                        "file_name": path.name,
                        "file_path": str(path),
                        "document_key": key,
                        "source_digest": digest,
                        "source_schema_version": SOURCE_SCHEMA_VERSION,
                        "page_status": "unlocated",
                        "parse_engine": parsed.engine,
                    },
                )
            )
    return documents


def persist_page_catalog(documents: list[Any], storage_dir: Path) -> None:
    pages = []
    # A page that held more than one window becomes several documents, and the
    # catalog lists pages, not documents: one entry per page.
    listed: set[tuple[str, int]] = set()
    for document in documents:
        meta = getattr(document, "metadata", {})
        if meta.get("source_schema_version") == SOURCE_SCHEMA_VERSION and "page_index" in meta:
            key = (str(meta.get("document_key") or ""), int(meta["page_index"]))
            if key in listed:
                continue
            listed.add(key)
            pages.append({k: v for k, v in meta.items() if k != "file_path"})
    if not pages:
        return
    target = storage_dir / CATALOG_FILENAME
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8")).get("pages", [])
        replaced = {p["document_key"] for p in pages}
        pages = [p for p in old if p.get("document_key") not in replaced] + pages
    temp = target.with_suffix(".tmp")
    temp.write_text(
        json.dumps({"schema_version": SOURCE_SCHEMA_VERSION, "pages": pages}, ensure_ascii=False),
        encoding="utf-8",
    )
    temp.replace(target)


def remove_page_catalog_sources(storage_dir: Path, document_keys: set[str]) -> int:
    """Drop the page entries of documents that left the knowledge base.

    The page catalog is a sidecar of the index: a document that is no longer
    part of the knowledge base must not keep its pages listed, or the reader
    would offer pages the index no longer holds. Returns the number of pages
    that were dropped.
    """
    if not document_keys:
        return 0
    target = Path(storage_dir) / CATALOG_FILENAME
    if not target.exists():
        return 0
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    pages = payload.get("pages", [])
    kept = [page for page in pages if page.get("document_key") not in document_keys]
    removed = len(pages) - len(kept)
    if not removed:
        return 0
    payload["pages"] = kept
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp.replace(target)
    return removed


def legacy_page_index(
    kb_dir: Path, storage_dir: Path, document_keys: list[str] | None, *, build: bool = False
) -> Path:
    """Compatibility sidecar: native page text + cached IR, no OCR or embedding.

    Old vectors cannot acquire trustworthy page locators by guessing. Use the
    BM25 engine over physical pages instead, without requiring optional stemming. Keep this
    explicitly distinct from a freshly rebuilt, hybrid page-aware vector index.
    """
    from deeptutor.services.parsing import cache, get_parse_service
    from deeptutor.services.parsing.engines.factory import get_parser
    from deeptutor.services.path_service import get_path_service

    raw = (kb_dir / "raw").resolve()
    candidates = (
        sorted(raw.rglob("*.pdf")) if document_keys is None else [raw / k for k in document_keys]
    )
    paths = [p for p in candidates if p.suffix.lower() == ".pdf" and p.is_file()]
    if not paths:
        raise SourcePageError("No selected PDF is available for page lookup.")
    try:
        engine = get_parse_service().active_engine()
        parser = get_parser(engine)
        signature = parser.signature(parser.resolve_config()).hash()
    except Exception:
        engine, signature = "native_pdf", "native-pdf-page-v1"
    inventory = []
    for path in paths:
        if not path.resolve().is_relative_to(raw):
            raise SourcePageError("A selected document is outside the knowledge-base directory.")
        digest = source_digest(path)
        hit = cache.lookup(get_path_service().get_parse_cache_root(), digest[:16], signature)
        inventory.append((path, digest, hit))
    identity = [
        (p.relative_to(raw).as_posix(), digest, signature if hit else "native-pdf-page-v1")
        for p, digest, hit in inventory
    ]
    key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:24]
    target = storage_dir / ".mastery-pages" / key
    if (target / CATALOG_FILENAME).is_file() and (target / "docstore.json").is_file():
        return target
    if not build:
        raise SourcePageError("The original-page lookup needs preparation. Retry the lesson.")
    from llama_index.core.node_parser import SentenceSplitter
    from llama_index.core.storage.docstore import SimpleDocumentStore

    documents = []
    for path, _, hit in inventory:
        markdown, blocks, assets = cache.load_ir(hit) if hit else ("", None, None)
        parsed = SimpleNamespace(
            markdown=markdown,
            blocks=blocks,
            asset_dir=assets,
            engine=engine if hit else "native_pdf",
            parser_signature=signature if hit else "native-pdf-page-v1",
        )
        documents.extend(build_pdf_documents(path, parsed, kb_dir))
    nodes = SentenceSplitter(chunk_size=512, chunk_overlap=50).get_nodes_from_documents(
        [d for d in documents if d.metadata.get("page_status") == "searchable"]
    )
    if not nodes:
        raise SourcePageError("These PDFs have no searchable page text. Finish their OCR first.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".preparing-", dir=target.parent) as temporary:
        stage = Path(temporary)
        docstore = SimpleDocumentStore()
        docstore.add_documents(nodes)
        docstore.persist(str(stage / "docstore.json"))
        persist_page_catalog(documents, stage)
        # The publication is atomic. Concurrent identical preparations may
        # reuse the first complete directory; neither changes the vector index.
        try:
            os.replace(stage, target)
        except OSError:
            if (
                not (target / CATALOG_FILENAME).is_file()
                or not (target / "docstore.json").is_file()
            ):
                raise
    return target
