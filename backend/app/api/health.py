"""System health routes.

GET  /api/v1/health                        , key metrics snapshot
GET  /api/v1/health/activity               , most recent 20 ingestion/query events
GET  /api/v1/health/document-performance   , per-document retrieval stats
POST /api/v1/health/reindex                , trigger full re-ingestion of all indexed documents
"""
import asyncio
import logging
import math
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.database import get_db, SessionLocal
from app.models import PolicyDocument, QueryLog, User
from app.retrieval import bm25_index as _bm25
from app.schemas.health import (
    ActivityEvent,
    ActivityResponse,
    DocumentPerformance,
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


@router.head("", include_in_schema=False)
def health_head() -> Response:
    # Render (and some reverse proxies) use HEAD for health checks.
    return Response(status_code=200)


@router.get("/activity", response_model=ActivityResponse)
def activity(
    current_admin: User = Depends(require_admin),
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
            description=f"{doc.file_name} , {doc.status}",
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

    out = events[:20]
    logger.info(
        "Health: activity feed admin_id=%s events_returned=%s",
        current_admin.id,
        len(out),
    )

    return ActivityResponse(events=out)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


@router.get("/document-performance", response_model=list[DocumentPerformance])
def document_performance(
    limit: int = Query(default=50, ge=1, le=200),
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[DocumentPerformance]:
    """Return per-document retrieval stats derived from stored retrieval traces.

    For each indexed document: number of queries that retrieved at least one
    chunk from it, and the average confidence % across those selected chunks.
    """
    docs = db.execute(
        select(PolicyDocument).where(PolicyDocument.status == "indexed")
    ).scalars().all()

    doc_map = {str(d.id): d.file_name for d in docs}

    # Aggregate from retrieval_trace JSON in Python , avoids complex JSON SQL
    logs = db.execute(
        select(QueryLog.retrieval_trace)
        .where(QueryLog.retrieval_trace.isnot(None))
    ).scalars().all()

    # doc_id → (query_count, [confidence values])
    stats: dict[str, dict] = {}
    for trace in logs:
        if not trace:
            continue
        seen_docs: set[str] = set()
        for entry in trace:
            if not entry.get("selected"):
                continue
            doc_id = entry.get("doc_id", "")
            if not doc_id or doc_id not in doc_map:
                continue
            rerank = entry.get("scores", {}).get("rerank", 0.0) or 0.0
            conf = _sigmoid(rerank)
            if doc_id not in stats:
                stats[doc_id] = {"count": 0, "scores": []}
            if doc_id not in seen_docs:
                stats[doc_id]["count"] += 1
                seen_docs.add(doc_id)
            stats[doc_id]["scores"].append(conf)

    result: list[DocumentPerformance] = []
    for doc_id, agg in stats.items():
        avg_conf = round(sum(agg["scores"]) / len(agg["scores"]) * 100, 1) if agg["scores"] else 0.0
        result.append(DocumentPerformance(
            doc_id=doc_id,
            file_name=doc_map.get(doc_id, doc_id),
            query_count=agg["count"],
            avg_confidence_pct=avg_conf,
        ))

    # Sort by avg_confidence ascending (struggling docs first)
    result.sort(key=lambda d: d.avg_confidence_pct)
    slice_ = result[:limit]

    logger.info(
        "Health: document-performance admin_id=%s limit=%s docs_returned=%s",
        current_admin.id,
        limit,
        len(slice_),
    )

    return slice_


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
                logger.warning("Reindex: PDF not found for %s , skipping", doc.file_name)
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
                logger.info("Reindex complete: %s , %d chunks", doc.file_name, chunk_count)

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
    current_admin: User = Depends(require_admin),
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

    logger.info(
        "Health: full reindex triggered admin_id=%s email=%s indexed_documents=%s",
        current_admin.id,
        current_admin.email,
        count,
    )

    return ReindexResponse(
        message="Full re-index started in background.",
        documents_queued=count,
    )
