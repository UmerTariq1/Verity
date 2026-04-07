"""Dense vector retrieval abstraction.

``ChromaVectorStore`` and ``PineconeVectorStore`` implement the same
``VectorStoreBase`` interface, switched at runtime via the ``VECTOR_STORE``
env var.  Call ``get_vector_store()`` to obtain the configured instance.

Metadata filtering (passed as the ``filters`` dict):
  category          — exact-match string
  owner_department  — exact-match string
  date_from         — effective_date >= value (ISO date string, e.g. "2024-01-01")
  date_to           — effective_date <= value (ISO date string)

Unknown filter keys are silently ignored so callers can pass a combined
RouteResult.filters dict without needing to strip unsupported keys.

Score semantics:
  Chroma returns L2 distances in cosine space; we convert to similarity via
  ``similarity = 1.0 - distance`` so all downstream code sees higher = better.
  Pinecone returns cosine similarity directly (already higher = better).
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_openai import OpenAIEmbeddings

from app.config import settings

logger = logging.getLogger(__name__)

_CHROMA_COLLECTION_NAME = "policy_documents"


# ── Shared result type ────────────────────────────────────────────────────────


@dataclass
class RetrievalResult:
    """A single retrieved chunk with all metadata needed by Phase 5 routes."""

    chunk_id: str
    doc_id: str
    text: str
    file_name: str
    page_number: int
    category: str
    owner_department: str
    effective_date: str
    score: float              # higher = more relevant (cosine similarity or cross-encoder logit)
    chunk_index: int = 0      # 1-based position within the parent document
    chunk_total: int | None = None  # total chunks for the parent document (None for legacy chunks)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )


def _parse_chunk_index(chunk_id: str) -> int:
    """Parse 1-based chunk index from the stable ID format ``<doc_id>__chunk_<i>``.

    Falls back to 0 for any chunk whose ID does not follow this pattern (e.g.
    chunks ingested before this convention was introduced).
    """
    try:
        suffix = chunk_id.split("__chunk_")[-1]
        return int(suffix) + 1
    except (ValueError, IndexError):
        return 0


def _row_to_result(
    chunk_id: str,
    text: str,
    metadata: dict,
    score: float,
) -> RetrievalResult:
    # chunk_index / chunk_total are stored in metadata for newly ingested docs.
    # For legacy chunks that predate this field, fall back to parsing the chunk_id.
    raw_index = metadata.get("chunk_index")
    chunk_index = int(raw_index) if raw_index is not None else _parse_chunk_index(chunk_id)

    raw_total = metadata.get("chunk_total")
    chunk_total = int(raw_total) if raw_total is not None else None

    return RetrievalResult(
        chunk_id=chunk_id,
        doc_id=metadata.get("doc_id", ""),
        text=text,
        file_name=metadata.get("file_name", ""),
        page_number=int(metadata.get("page_number", 0)),
        category=metadata.get("category", ""),
        owner_department=metadata.get("owner_department", ""),
        effective_date=metadata.get("effective_date", ""),
        score=score,
        chunk_index=chunk_index,
        chunk_total=chunk_total,
    )


# ── Abstract base ─────────────────────────────────────────────────────────────


class VectorStoreBase(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        top_n: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        """Return top-N chunks by similarity, with optional metadata pre-filtering."""


# ── Chroma implementation ─────────────────────────────────────────────────────


class ChromaVectorStore(VectorStoreBase):
    def __init__(self) -> None:
        import chromadb

        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        self._collection = client.get_or_create_collection(
            name=_CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _build_where(self, filters: dict[str, Any]) -> dict | None:
        """Translate canonical filter keys into a Chroma ``where`` clause."""
        clauses: list[dict] = []

        if filters.get("category"):
            clauses.append({"category": {"$eq": filters["category"]}})
        if filters.get("owner_department"):
            clauses.append({"owner_department": {"$eq": filters["owner_department"]}})
        if filters.get("date_from"):
            clauses.append({"effective_date": {"$gte": filters["date_from"]}})
        if filters.get("date_to"):
            clauses.append({"effective_date": {"$lte": filters["date_to"]}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def search(
        self,
        query: str,
        top_n: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        embedding = _get_embeddings().embed_query(query)
        where = self._build_where(filters or {})

        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": top_n,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        try:
            raw = self._collection.query(**kwargs)
        except Exception:
            logger.exception("Chroma query failed")
            return []

        ids: list[str] = raw["ids"][0]
        documents: list[str] = raw["documents"][0]
        metadatas: list[dict] = raw["metadatas"][0]
        # Chroma cosine distance = 1 − cosine_similarity → invert to get similarity
        distances: list[float] = raw["distances"][0]

        return [
            _row_to_result(chunk_id, text, meta, 1.0 - dist)
            for chunk_id, text, meta, dist in zip(ids, documents, metadatas, distances)
        ]


# ── Pinecone implementation ───────────────────────────────────────────────────


class PineconeVectorStore(VectorStoreBase):
    def __init__(self) -> None:
        from pinecone import Pinecone

        pc = Pinecone(api_key=settings.pinecone_api_key)
        self._index = pc.Index(settings.pinecone_index_name)

    def _build_filter(self, filters: dict[str, Any]) -> dict | None:
        """Translate canonical filter keys into a Pinecone metadata filter."""
        clauses: list[dict] = []

        if filters.get("category"):
            clauses.append({"category": {"$eq": filters["category"]}})
        if filters.get("owner_department"):
            clauses.append({"owner_department": {"$eq": filters["owner_department"]}})
        if filters.get("date_from"):
            clauses.append({"effective_date": {"$gte": filters["date_from"]}})
        if filters.get("date_to"):
            clauses.append({"effective_date": {"$lte": filters["date_to"]}})

        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    def search(
        self,
        query: str,
        top_n: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievalResult]:
        embedding = _get_embeddings().embed_query(query)
        pinecone_filter = self._build_filter(filters or {})

        kwargs: dict[str, Any] = {
            "vector": embedding,
            "top_k": top_n,
            "include_metadata": True,
        }
        if pinecone_filter:
            kwargs["filter"] = pinecone_filter

        try:
            raw = self._index.query(**kwargs)
        except Exception:
            logger.exception("Pinecone query failed")
            return []

        results: list[RetrievalResult] = []
        for match in raw.get("matches", []):
            meta = dict(match.get("metadata", {}))
            # Pinecone stores chunk text in the metadata "text" field (see embedder.py)
            text = meta.pop("text", "")
            results.append(
                _row_to_result(match["id"], text, meta, float(match.get("score", 0.0)))
            )
        return results


# ── Factory ───────────────────────────────────────────────────────────────────


def get_vector_store() -> VectorStoreBase:
    """Return the vector store instance selected by the ``VECTOR_STORE`` env var."""
    if settings.vector_store == "chroma":
        return ChromaVectorStore()
    return PineconeVectorStore()
