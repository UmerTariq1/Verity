"""Query log routes (admin only).

GET /api/v1/logs                   — paginated log list with filters
GET /api/v1/logs/export            — CSV download (must come before /{id} route)
GET /api/v1/logs/low-confidence    — recent logs where avg confidence < threshold
GET /api/v1/logs/{id}              — log detail with receipt + chunk snippets
"""
import csv
import io
import math
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.database import get_db
from app.models import PolicyDocument, QueryLog, User
from app.schemas.log import (
    LowConfidenceLog,
    LogChunkSnippet,
    LogDetail,
    LogListResponse,
    LogReceiptEntry,
    LogSummary,
)

router = APIRouter(prefix="/logs", tags=["logs"])

_LOW_CONF_DEFAULT = 0.60   # sigmoid-normalised avg below this → low confidence


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _fetch_chunk_snippets(chunk_ids: list[str]) -> list[LogChunkSnippet]:
    """Fetch chunk text and metadata live from Chroma for the log detail view."""
    if not chunk_ids:
        return []
    try:
        import chromadb
        from app.config import settings

        client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
        collection = client.get_or_create_collection(
            name="policy_documents",
            metadata={"hnsw:space": "cosine"},
        )
        result = collection.get(ids=chunk_ids, include=["documents", "metadatas"])
        snippets: list[LogChunkSnippet] = []
        for chunk_id, text, meta in zip(
            result["ids"],
            result["documents"] or [],
            result["metadatas"] or [],
        ):
            snippets.append(LogChunkSnippet(
                chunk_id=chunk_id,
                text_snippet=(text or "")[:400],
                file_name=meta.get("file_name", ""),
                page_number=int(meta.get("page_number", 0)),
            ))
        return snippets
    except Exception:
        return []


def _build_receipt(trace: list | None) -> list[LogReceiptEntry]:
    """Convert the stored retrieval_trace JSON into LogReceiptEntry objects."""
    if not trace:
        return []
    entries: list[LogReceiptEntry] = []
    for item in trace:
        rerank_score = item.get("scores", {}).get("rerank", 0.0) or 0.0
        confidence_pct = round(_sigmoid(rerank_score) * 100, 1)
        entries.append(LogReceiptEntry(
            chunk_id=item.get("chunk_id", ""),
            doc_id=item.get("doc_id", ""),
            file_name=item.get("file_name", ""),
            page_number=item.get("page_number", 0),
            preview=item.get("preview", ""),
            confidence_pct=confidence_pct,
            method=item.get("method", "semantic_match"),
            selected=bool(item.get("selected", False)),
        ))
    return entries


def _row_to_summary(log: QueryLog, user: User | None) -> LogSummary:
    data = LogSummary.model_validate(log)
    data.user_name = user.name if user else None
    data.user_email = user.email if user else None
    return data


@router.get("", response_model=LogListResponse)
def list_logs(
    user_search: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    feedback: str = "",
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LogListResponse:
    """Return a paginated list of query logs with optional filters."""
    stmt = select(QueryLog, User).join(User, QueryLog.user_id == User.id, isouter=True)

    if user_search:
        term = f"%{user_search}%"
        stmt = stmt.where(User.name.ilike(term) | User.email.ilike(term))
    if date_from:
        stmt = stmt.where(QueryLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(QueryLog.created_at <= date_to)
    if feedback:
        stmt = stmt.where(QueryLog.feedback == feedback)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    rows = db.execute(
        stmt.order_by(QueryLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).all()

    items = [_row_to_summary(log, user) for log, user in rows]
    return LogListResponse(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_logs(
    user_search: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    feedback: str = "",
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream all matching query logs as a CSV download."""
    stmt = select(QueryLog, User).join(User, QueryLog.user_id == User.id, isouter=True)

    if user_search:
        term = f"%{user_search}%"
        stmt = stmt.where(User.name.ilike(term) | User.email.ilike(term))
    if date_from:
        stmt = stmt.where(QueryLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(QueryLog.created_at <= date_to)
    if feedback:
        stmt = stmt.where(QueryLog.feedback == feedback)

    rows = db.execute(stmt.order_by(QueryLog.created_at.desc())).all()

    def _generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "id", "user_id", "user_name", "user_email", "query_text",
            "retrieved_chunk_ids", "relevance_scores", "date_filter_from",
            "date_filter_to", "feedback", "response_latency_ms", "created_at",
            "langsmith_trace_url",
        ])
        yield buffer.getvalue()

        for log, user in rows:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                str(log.id),
                str(log.user_id),
                user.name if user else "",
                user.email if user else "",
                log.query_text,
                ",".join(log.retrieved_chunk_ids or []),
                ",".join(str(s) for s in (log.relevance_scores or [])),
                log.date_filter_from or "",
                log.date_filter_to or "",
                log.feedback or "",
                log.response_latency_ms or "",
                log.created_at.isoformat(),
                log.langsmith_trace_url or "",
            ])
            yield buffer.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=verity_query_logs.csv"},
    )


@router.get("/low-confidence")
def low_confidence_logs(
    threshold: float = Query(default=_LOW_CONF_DEFAULT, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[LowConfidenceLog]:
    """Return recent logs where avg selected-chunk confidence < threshold.

    Confidence is sigmoid-normalised cross-encoder score averaged over the
    selected chunks stored in retrieval_trace.
    """
    rows = db.execute(
        select(QueryLog, User)
        .join(User, QueryLog.user_id == User.id, isouter=True)
        .where(QueryLog.retrieval_trace.isnot(None))
        .order_by(QueryLog.created_at.desc())
        .limit(500)  # scan recent logs; filter in Python
    ).all()

    results: list[LowConfidenceLog] = []
    for log, user in rows:
        trace = log.retrieval_trace or []
        selected = [e for e in trace if e.get("selected")]
        if not selected:
            continue
        avg_conf = sum(_sigmoid(e.get("scores", {}).get("rerank", 0.0) or 0.0) for e in selected) / len(selected)
        if avg_conf < threshold:
            results.append(LowConfidenceLog(
                id=log.id,
                query_text=log.query_text,
                avg_confidence_pct=round(avg_conf * 100, 1),
                created_at=log.created_at,
                user_name=user.name if user else None,
                langsmith_trace_url=log.langsmith_trace_url,
            ))
        if len(results) >= limit:
            break

    return results


@router.get("/{log_id}", response_model=LogDetail)
def get_log(
    log_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LogDetail:
    """Return full log detail including a structured retrieval receipt."""
    row = db.execute(
        select(QueryLog, User)
        .join(User, QueryLog.user_id == User.id, isouter=True)
        .where(QueryLog.id == log_id)
    ).one_or_none()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")

    log, user = row

    # Prefer retrieval_trace for chunk snippets (it already has previews + metadata).
    # Fall back to live Chroma fetch for legacy logs that predate this feature.
    if log.retrieval_trace:
        snippets = [
            LogChunkSnippet(
                chunk_id=e.get("chunk_id", ""),
                text_snippet=e.get("preview", ""),
                file_name=e.get("file_name", ""),
                page_number=e.get("page_number", 0),
            )
            for e in log.retrieval_trace
            if e.get("selected")
        ]
    else:
        snippets = _fetch_chunk_snippets(log.retrieved_chunk_ids or [])

    receipt = _build_receipt(log.retrieval_trace)
    summary = _row_to_summary(log, user)
    return LogDetail(**summary.model_dump(), chunk_snippets=snippets, retrieval_receipt=receipt)
