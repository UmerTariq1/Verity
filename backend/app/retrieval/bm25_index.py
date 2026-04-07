"""BM25 sparse retrieval index.

Built as a module-level singleton on startup via ``build_bm25_index()``.

BM25Okapi is not serialisable across processes, so the index is rebuilt from
the Chroma collection on every container start (~200ms for 10 k chunks — an
acceptable startup cost documented in README "Retrieval Design Decisions").

The Chroma collection fetched here is the same "policy_documents" collection
written by embedder.py.  Chunk IDs follow the pattern <doc_id>__chunk_<index>,
and chunk metadata carries the full set of fields written during ingestion.

Tokenisation: simple whitespace lowercasing — consistent with the chunk text
stored in Chroma (no extra normalisation needed; BM25 ranking is robust to
minor tokenisation differences between index and query time).
"""
import logging
from dataclasses import dataclass, field

from rank_bm25 import BM25Okapi

from app.config import settings

logger = logging.getLogger(__name__)

_CHROMA_COLLECTION_NAME = "policy_documents"


# ── Module-level singleton state ──────────────────────────────────────────────


@dataclass
class _BM25State:
    index: BM25Okapi | None = None
    chunk_ids: list[str] = field(default_factory=list)
    chunk_texts: list[str] = field(default_factory=list)
    chunk_metadatas: list[dict] = field(default_factory=list)
    ready: bool = False


_state = _BM25State()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> list[str]:
    """Lowercase whitespace tokeniser — applied consistently at index and query time."""
    return text.lower().split()


# ── Public API ────────────────────────────────────────────────────────────────


def build_bm25_index() -> None:
    """Fetch all chunks from Chroma and build the in-memory BM25Okapi index.

    Safe to call multiple times — each call does a full rebuild (e.g. after a
    re-index operation triggered by the admin panel in Phase 5).

    Should be called once from the FastAPI lifespan hook so the first query is
    never slow.  Returns immediately if Chroma is empty (logs a warning).
    """
    if not settings.bm25_enabled:
        logger.info("BM25 index build skipped (BM25 disabled).")
        _state.ready = False
        return

    # BM25 is currently built from the local Chroma collection.
    # In production (Pinecone), skip building BM25 to avoid loading large corpora into memory.
    if settings.vector_store != "chroma":
        logger.info("BM25 index build skipped (vector_store=%s).", settings.vector_store)
        _state.ready = False
        return

    import chromadb

    logger.info("Building BM25 index from Chroma collection '%s'…", _CHROMA_COLLECTION_NAME)

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    collection = client.get_or_create_collection(
        name=_CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    result = collection.get(include=["documents", "metadatas"])

    chunk_ids: list[str] = result["ids"]
    chunk_texts: list[str] = result["documents"] or []
    chunk_metadatas: list[dict] = result["metadatas"] or []

    if not chunk_texts:
        logger.warning(
            "BM25 index: no chunks found in Chroma — BM25 will return empty results "
            "until documents are ingested and build_bm25_index() is called again"
        )
        _state.ready = False
        return

    tokenized = [_tokenize(t) for t in chunk_texts]
    _state.index = BM25Okapi(tokenized)
    _state.chunk_ids = chunk_ids
    _state.chunk_texts = chunk_texts
    _state.chunk_metadatas = chunk_metadatas
    _state.ready = True

    logger.info("BM25 index ready — %d chunks indexed", len(chunk_ids))


def search(
    query: str,
    top_n: int = 20,
) -> list[tuple[str, float, str, dict]]:
    """Return the top-N chunks by BM25 score.

    Args:
        query: The raw user query string.
        top_n: Maximum number of results to return.

    Returns:
        List of ``(chunk_id, bm25_score, chunk_text, metadata)`` tuples ordered
        by descending BM25 score.  Returns an empty list if the index is not
        ready (no chunks have been ingested yet).
    """
    if not _state.ready or _state.index is None:
        logger.warning("BM25 search called but index is not ready — returning empty results")
        return []

    tokens = _tokenize(query)
    scores: list[float] = _state.index.get_scores(tokens).tolist()

    ranked = sorted(
        zip(_state.chunk_ids, scores, _state.chunk_texts, _state.chunk_metadatas),
        key=lambda x: x[1],
        reverse=True,
    )

    return [(cid, score, text, meta) for cid, score, text, meta in ranked[:top_n]]


def is_ready() -> bool:
    """Return True if the BM25 index has been built and contains at least one chunk."""
    return _state.ready


def chunk_count() -> int:
    """Return the number of chunks currently in the BM25 index."""
    return len(_state.chunk_ids)
