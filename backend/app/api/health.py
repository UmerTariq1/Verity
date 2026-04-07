"""System health routes (admin only).

GET  /api/v1/health            — key metrics snapshot
GET  /api/v1/health/activity   — most recent 20 ingestion/query events
POST /api/v1/health/reindex    — trigger full re-ingestion of all indexed documents
"""
import asyncio
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.database import get_db, SessionLocal
from app.models import PolicyDocument, QueryLog, User
from app.retrieval import bm25_index as _bm25
from app.schemas.health import (
    ActivityEvent,
    ActivityResponse,
    HealthResponse,
    ReindexResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


def _last_indexed_at(db: Session) -> datetime | None:
    """Return the created_at timestamp of the most recently indexed document."""
    row = db.execute(
        select(PolicyDocument.created_at)
        .where(PolicyDocument.status == "indexed")
        .order_by(PolicyDocument.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return row


def _avg_relevance(db: Session) -> float | None:
    """Return the average of all stored relevance_scores across all logs."""
    logs = db.execute(
        select(QueryLog.relevance_scores).where(QueryLog.relevance_scores.isnot(None))
    ).scalars().all()

    all_scores: list[float] = []
    for scores in logs:
        if isinstance(scores, list):
            all_scores.extend(float(s) for s in scores if s is not None)

    return round(sum(all_scores) / len(all_scores), 4) if all_scores else None


@router.get("", response_model=HealthResponse)
def health(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HealthResponse:
    """Return a metrics snapshot for the system health dashboard."""
    total_documents = db.execute(
        select(func.count()).select_from(PolicyDocument)
    ).scalar_one()

    total_chunks_row = db.execute(
        select(func.sum(PolicyDocument.chunk_count))
        .where(PolicyDocument.status == "indexed")
    ).scalar_one()
    total_chunks = int(total_chunks_row or 0)

    today = date.today()
    queries_today = db.execute(
        select(func.count()).select_from(QueryLog)
        .where(func.date(QueryLog.created_at) == today)
    ).scalar_one()

    return HealthResponse(
        total_documents=total_documents,
        total_chunks=total_chunks,
        avg_relevance_score=_avg_relevance(db),
        queries_today=queries_today,
        index_status="ready" if _bm25.is_ready() else "empty",
        vector_store_type=settings.vector_store,
        last_indexed_at=_last_indexed_at(db),
    )


@router.get("/activity", response_model=ActivityResponse)
def activity(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ActivityResponse:
    """Return the 20 most recent ingestion and query events for the activity feed."""
    recent_docs = db.execute(
        select(PolicyDocument)
        .order_by(PolicyDocument.created_at.desc())
        .limit(10)
    ).scalars().all()

    recent_logs = db.execute(
        select(QueryLog)
        .order_by(QueryLog.created_at.desc())
        .limit(10)
    ).scalars().all()

    events: list[ActivityEvent] = []

    for doc in recent_docs:
        events.append(ActivityEvent(
            event_type="ingestion",
            description=f"{doc.file_name} — {doc.status}",
            created_at=doc.created_at,
        ))

    for log in recent_logs:
        snippet = log.query_text[:80] + ("…" if len(log.query_text) > 80 else "")
        events.append(ActivityEvent(
            event_type="query",
            description=snippet,
            created_at=log.created_at,
        ))

    events.sort(key=lambda e: e.created_at, reverse=True)

    return ActivityResponse(events=events[:20])


def _reindex_all_sync() -> int:
    """Re-ingest all currently indexed documents. Runs in a background thread pool.

    Opens its own DB session; rebuilds BM25 once after all documents are processed.
    """
    from app.ingestion.startup_ingestor import DATA_DIR
    from app.ingestion.chunker import get_splitter
    from app.ingestion.embedder import delete_chunks, embed_and_store
    from app.ingestion.pdf_extractor import extract_pages, IngestionError

    db: Session = SessionLocal()
    queued = 0
    try:
        docs = db.execute(
            select(PolicyDocument).where(PolicyDocument.status == "indexed")
        ).scalars().all()

        for doc in docs:
            pdf_path = DATA_DIR / doc.file_name
            if not pdf_path.exists():
                logger.warning("Reindex: PDF not found for %s — skipping", doc.file_name)
                continue

            db.execute(
                update(PolicyDocument)
                .where(PolicyDocument.id == doc.id)
                .values(status="queued", chunk_count=0)
            )
            db.commit()
            queued += 1

            try:
                delete_chunks(doc.id)
                db.execute(
                    update(PolicyDocument)
                    .where(PolicyDocument.id == doc.id)
                    .values(status="processing")
                )
                db.commit()

                pages = extract_pages(pdf_path)
                splitter = get_splitter()
                chunks: list[dict] = []
                for page in pages:
                    if not page["text"]:
                        continue
                    for chunk_text in splitter.split_text(page["text"]):
                        stripped = chunk_text.strip()
                        if stripped:
                            chunks.append({"text": stripped, "page_number": page["page_number"]})

                if not chunks:
                    raise IngestionError(f"No chunks from {doc.file_name}")

                doc_metadata = {
                    "file_name": doc.file_name,
                    "category": doc.category,
                    "owner_department": doc.owner_department,
                    "effective_date": doc.effective_date,
                }
                chunk_count = embed_and_store(doc.id, chunks, doc_metadata, db)
                db.execute(
                    update(PolicyDocument)
                    .where(PolicyDocument.id == doc.id)
                    .values(status="indexed", chunk_count=chunk_count)
                )
                db.commit()
                logger.info("Reindex complete: %s — %d chunks", doc.file_name, chunk_count)

            except Exception as exc:
                logger.error("Reindex failed for %s: %s", doc.file_name, exc, exc_info=True)
                db.execute(
                    update(PolicyDocument)
                    .where(PolicyDocument.id == doc.id)
                    .values(status="failed")
                )
                db.commit()

        # Rebuild BM25 once after all documents are re-embedded
        _bm25.build_bm25_index()
    finally:
        db.close()

    return queued


@router.post("/reindex", response_model=ReindexResponse, status_code=202)
async def full_reindex(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReindexResponse:
    """Trigger full re-ingestion of all indexed documents.

    Returns immediately with the count of documents queued.
    Re-embedding and BM25 rebuild run in the default thread-pool executor.
    """
    count = db.execute(
        select(func.count()).select_from(PolicyDocument)
        .where(PolicyDocument.status == "indexed")
    ).scalar_one()

    loop = asyncio.get_event_loop()
    asyncio.create_task(loop.run_in_executor(None, _reindex_all_sync))

    return ReindexResponse(
        message="Full re-index started in background.",
        documents_queued=count,
    )
