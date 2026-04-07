"""Embed document chunks and store them in the configured vector store.

Supports Chroma (local dev) and Pinecone (production), switched via the
VECTOR_STORE env var.  The vector store abstraction used here is intentionally
minimal — Phase 4 introduces the full VectorStore interface for retrieval.

Chunk metadata stored alongside every vector:
  doc_id            — PolicyDocument.id (UUID as string); used by Phase 4 retrieval
  file_name         — original PDF filename
  category          — policy category
  owner_department  — owning department
  effective_date    — ISO date string
  page_number       — source page inside the PDF

After all chunks are stored, chunk_count is written back to the
policy_documents row so the DB stays in sync with the vector store.
"""
import logging
import uuid
from typing import Any

from langchain_openai import OpenAIEmbeddings
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PolicyDocument

logger = logging.getLogger(__name__)

_CHROMA_COLLECTION_NAME = "policy_documents"
_PINECONE_BATCH_SIZE = 100


# ── Internal helpers ──────────────────────────────────────────────────────────


def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model="text-embedding-3-small",
        openai_api_key=settings.openai_api_key,
    )


def _get_chroma_collection():
    import chromadb

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    return client.get_or_create_collection(
        name=_CHROMA_COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def _build_chunk_ids(doc_id: uuid.UUID, count: int) -> list[str]:
    """Generate stable, sortable IDs: <doc_id>__chunk_<index>."""
    return [f"{doc_id}__chunk_{i}" for i in range(count)]


def _build_metadatas(
    doc_id: uuid.UUID,
    chunks: list[dict[str, Any]],
    doc_metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    total = len(chunks)
    return [
        {
            "doc_id": str(doc_id),
            "file_name": doc_metadata["file_name"],
            "category": doc_metadata["category"],
            "owner_department": doc_metadata["owner_department"],
            "effective_date": str(doc_metadata["effective_date"]),
            "page_number": chunk["page_number"],
            "chunk_index": i + 1,   # 1-based position within this document
            "chunk_total": total,   # total chunks for this document
        }
        for i, chunk in enumerate(chunks)
    ]


def _store_in_chroma(
    chunk_ids: list[str],
    texts: list[str],
    metadatas: list[dict[str, Any]],
    embeddings_model: OpenAIEmbeddings,
) -> None:
    collection = _get_chroma_collection()
    vectors = embeddings_model.embed_documents(texts)
    collection.upsert(
        ids=chunk_ids,
        embeddings=vectors,
        documents=texts,
        metadatas=metadatas,
    )


def _store_in_pinecone(
    chunk_ids: list[str],
    texts: list[str],
    metadatas: list[dict[str, Any]],
    embeddings_model: OpenAIEmbeddings,
) -> None:
    from pinecone import Pinecone

    pc = Pinecone(api_key=settings.pinecone_api_key)
    index = pc.Index(settings.pinecone_index_name)

    vectors = embeddings_model.embed_documents(texts)
    upsert_data = [
        {
            "id": chunk_id,
            "values": vector,
            "metadata": {**meta, "text": text},
        }
        for chunk_id, vector, meta, text in zip(chunk_ids, vectors, metadatas, texts)
    ]

    for start in range(0, len(upsert_data), _PINECONE_BATCH_SIZE):
        batch = upsert_data[start : start + _PINECONE_BATCH_SIZE]
        index.upsert(vectors=batch)


# ── Public API ────────────────────────────────────────────────────────────────


def embed_and_store(
    doc_id: uuid.UUID,
    chunks: list[dict[str, Any]],
    doc_metadata: dict[str, Any],
    db: Session,
) -> int:
    """Embed chunks, upsert into the vector store, and write chunk_count to the DB.

    Args:
        doc_id:       PolicyDocument.id for the parent document.
        chunks:       List of {"text": str, "page_number": int} dicts.
        doc_metadata: Dict with keys file_name, category, owner_department, effective_date.
        db:           Active SQLAlchemy session (caller owns the lifecycle).

    Returns:
        Number of chunks stored (may be 0 if chunks list is empty).

    Raises:
        Any exception from the embedding model or vector store — caller handles
        the status transition to "failed".
    """
    if not chunks:
        logger.warning("embed_and_store called with empty chunk list for doc_id=%s", doc_id)
        return 0

    texts = [chunk["text"] for chunk in chunks]
    chunk_ids = _build_chunk_ids(doc_id, len(chunks))
    metadatas = _build_metadatas(doc_id, chunks, doc_metadata)

    embeddings_model = _get_embeddings()

    if settings.vector_store == "chroma":
        logger.debug("Upserting %d chunks to Chroma for doc_id=%s", len(chunks), doc_id)
        _store_in_chroma(chunk_ids, texts, metadatas, embeddings_model)
    else:
        logger.debug("Upserting %d chunks to Pinecone for doc_id=%s", len(chunks), doc_id)
        _store_in_pinecone(chunk_ids, texts, metadatas, embeddings_model)

    db.execute(
        update(PolicyDocument)
        .where(PolicyDocument.id == doc_id)
        .values(chunk_count=len(chunks))
    )
    db.commit()

    logger.info(
        "Stored %d chunks in %s for doc_id=%s",
        len(chunks),
        settings.vector_store,
        doc_id,
    )
    return len(chunks)


def delete_chunks(doc_id: uuid.UUID) -> None:
    """Remove all chunks belonging to doc_id from the vector store.

    Called by the delete-document API route (Phase 5) and the re-index route.
    No-op if the document has no chunks in the store.
    """
    if settings.vector_store == "chroma":
        collection = _get_chroma_collection()
        collection.delete(where={"doc_id": str(doc_id)})
        logger.info("Deleted Chroma chunks for doc_id=%s", doc_id)
    else:
        from pinecone import Pinecone

        pc = Pinecone(api_key=settings.pinecone_api_key)
        index = pc.Index(settings.pinecone_index_name)
        index.delete(filter={"doc_id": {"$eq": str(doc_id)}})
        logger.info("Deleted Pinecone vectors for doc_id=%s", doc_id)
