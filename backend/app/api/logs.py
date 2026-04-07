"""Query log routes (admin only).

GET /api/v1/logs             — paginated log list with filters
GET /api/v1/logs/export      — CSV download (must come before /{id} route)
GET /api/v1/logs/{id}        — log detail with live chunk text from Chroma
"""
import csv
import io
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.database import get_db
from app.models import QueryLog, User
from app.schemas.log import LogChunkSnippet, LogDetail, LogListResponse, LogSummary

router = APIRouter(prefix="/logs", tags=["logs"])


def _fetch_chunk_snippets(chunk_ids: list[str]) -> list[LogChunkSnippet]:
    """Fetch chunk text and metadata live from Chroma for the log detail view.

    Returns an empty list if Chroma is unavailable or the chunks were deleted.
    The AI response text is intentionally NOT stored (see BRD §7).
    """
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
        result = collection.get(
            ids=chunk_ids,
            include=["documents", "metadatas"],
        )
        snippets: list[LogChunkSnippet] = []
        for chunk_id, text, meta in zip(
            result["ids"],
            result["documents"] or [],
            result["metadatas"] or [],
        ):
            snippets.append(
                LogChunkSnippet(
                    chunk_id=chunk_id,
                    text_snippet=(text or "")[:400],
                    file_name=meta.get("file_name", ""),
                    page_number=int(meta.get("page_number", 0)),
                )
            )
        return snippets
    except Exception:
        return []


def _build_log_filter(
    stmt,
    user_id: str,
    date_from: date | None,
    date_to: date | None,
    feedback: str,
):
    """Apply optional filters to a QueryLog select statement."""
    if user_id:
        stmt = stmt.where(QueryLog.user_id == user_id)
    if date_from:
        stmt = stmt.where(QueryLog.created_at >= date_from)
    if date_to:
        stmt = stmt.where(QueryLog.created_at <= date_to)
    if feedback:
        stmt = stmt.where(QueryLog.feedback == feedback)
    return stmt


@router.get("", response_model=LogListResponse)
def list_logs(
    user_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    feedback: str = "",
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LogListResponse:
    """Return a paginated list of query logs with optional filters."""
    base_stmt = select(QueryLog)
    base_stmt = _build_log_filter(base_stmt, user_id, date_from, date_to, feedback)

    total = db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    ).scalar_one()

    items = db.execute(
        base_stmt.order_by(QueryLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    return LogListResponse(
        items=[LogSummary.model_validate(log) for log in items],
        total=total,
        page=page,
        size=size,
    )


@router.get("/export")
def export_logs(
    user_id: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    feedback: str = "",
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """Stream all matching query logs as a CSV download."""
    stmt = select(QueryLog)
    stmt = _build_log_filter(stmt, user_id, date_from, date_to, feedback)
    logs = db.execute(stmt.order_by(QueryLog.created_at.desc())).scalars().all()

    def _generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "id", "user_id", "query_text", "retrieved_chunk_ids",
            "relevance_scores", "date_filter_from", "date_filter_to",
            "feedback", "response_latency_ms", "created_at",
        ])
        yield buffer.getvalue()

        for log in logs:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                str(log.id),
                str(log.user_id),
                log.query_text,
                ",".join(log.retrieved_chunk_ids or []),
                ",".join(str(s) for s in (log.relevance_scores or [])),
                log.date_filter_from or "",
                log.date_filter_to or "",
                log.feedback or "",
                log.response_latency_ms or "",
                log.created_at.isoformat(),
            ])
            yield buffer.getvalue()

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=verity_query_logs.csv"},
    )


@router.get("/{log_id}", response_model=LogDetail)
def get_log(
    log_id: uuid.UUID,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> LogDetail:
    """Return full log detail including live chunk text snippets from Chroma."""
    log = db.execute(
        select(QueryLog).where(QueryLog.id == log_id)
    ).scalar_one_or_none()

    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")

    snippets = _fetch_chunk_snippets(log.retrieved_chunk_ids or [])

    summary = LogSummary.model_validate(log)
    return LogDetail(**summary.model_dump(), chunk_snippets=snippets)
