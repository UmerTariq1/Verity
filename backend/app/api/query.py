"""Query routes.

GET  /api/v1/query/history              — current user's own query history
POST /api/v1/query                      — hybrid RAG query
POST /api/v1/query/{log_id}/feedback    — thumbs up/down on a previous answer
"""
import math
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models import PolicyDocument, QueryLog, User
from app.retrieval.hybrid_retriever import retrieve
from app.retrieval.query_router import route_query
from app.schemas.log import LogSummary, UserHistoryResponse
from app.schemas.query import FeedbackRequest, QueryRequest, QueryResponse, SourceChunk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# Confidence threshold: avg sigmoid-normalised rerank score across selected chunks.
# Below this we surface a low-confidence notice to the user.
_LOW_CONFIDENCE_THRESHOLD = 0.60

# Number of "rejected" chunks to surface in the explainability panel.
_REJECTED_SOURCES_COUNT = 5


def _sigmoid(x: float) -> float:
    """Sigmoid normalisation — maps cross-encoder logits to [0, 1]."""
    return 1.0 / (1.0 + math.exp(-x))


def _build_gpt_answer(query: str, sources: list[SourceChunk]) -> str:
    """Call gpt-5-nano and return the answer string."""
    try:
        from openai import OpenAI
        from app.config import settings

        context_blocks = [
            f"[{i + 1}] (from {s.file_name}, page {s.page}):\n{s.text_snippet}"
            for i, s in enumerate(sources)
        ]
        context = "\n\n".join(context_blocks)

        system_prompt = (
            "You are Verity, an intelligent HR policy assistant for Nexora GmbH. "
            "Answer the user's question using only the provided policy excerpts. "
            "Cite sources by their bracket number when referencing specific policies. "
            "If the answer cannot be determined from the excerpts, say so clearly. "
        )
        user_message = f"Context:\n{context}\n\nQuestion: {query}"

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-5-nano",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        return response.choices[0].message.content or "No answer generated."
    except Exception as exc:
        logger.error("gpt-5-nano call failed: %s", exc)
        return (
            "I was unable to generate an answer at this time. "
            "Please review the source excerpts below."
        )


def _try_get_langsmith_run() -> tuple[str | None, str | None]:
    """Return (run_id, trace_url) for the current LangSmith trace, or (None, None)."""
    try:
        from langsmith import get_current_run_tree  # type: ignore[import]
        run = get_current_run_tree()
        if run is None:
            return None, None
        run_id = str(run.id)
        # Build the canonical LangSmith trace URL from the project and run id.
        from app.config import settings
        project = getattr(settings, "langchain_project", None) or "default"
        trace_url = f"https://smith.langchain.com/o/projects/p/{project}/r/{run_id}"
        return run_id, trace_url
    except Exception:
        return None, None


@router.get("/history", response_model=UserHistoryResponse)
def query_history(
    page: int = 1,
    size: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserHistoryResponse:
    """Return the current user's own query history, newest first."""
    stmt = select(QueryLog).where(QueryLog.user_id == current_user.id)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    logs = db.execute(
        stmt.order_by(QueryLog.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    items = []
    for log in logs:
        summary = LogSummary.model_validate(log)
        summary.user_name = current_user.name
        summary.user_email = current_user.email
        items.append(summary)

    return UserHistoryResponse(items=items, total=total, page=page, size=size)


@router.post("", response_model=QueryResponse)
def query(
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryResponse:
    """Run the hybrid retrieval pipeline and return a gpt-5-nano answer with sources."""
    start_ms = time.monotonic()

    # ── Fetch known categories for the router ─────────────────────────────────
    rows = db.execute(
        select(PolicyDocument.category).distinct()
    ).scalars().all()
    known_categories: list[str] = [r for r in rows if r]

    # ── Route the query ───────────────────────────────────────────────────────
    route = route_query(body.query_text, known_categories=known_categories)

    filters = dict(route.filters)
    if body.date_from:
        filters["date_from"] = body.date_from.isoformat()
    if body.date_to:
        filters["date_to"] = body.date_to.isoformat()
    if body.category:
        filters["category"] = body.category

    retrieval_trace_json: list | None = None
    langsmith_run_id: str | None = None
    langsmith_trace_url: str | None = None

    if route.route == "metadata":
        query_stmt = select(PolicyDocument).where(PolicyDocument.status == "indexed")
        if filters.get("category"):
            query_stmt = query_stmt.where(PolicyDocument.category == filters["category"])
        if filters.get("date_from"):
            from datetime import date as _date
            query_stmt = query_stmt.where(
                PolicyDocument.effective_date >= _date.fromisoformat(filters["date_from"])
            )
        if filters.get("date_to"):
            from datetime import date as _date
            query_stmt = query_stmt.where(
                PolicyDocument.effective_date <= _date.fromisoformat(filters["date_to"])
            )

        docs = db.execute(query_stmt).scalars().all()
        answer = (
            f"Found {len(docs)} indexed document(s):\n"
            + "\n".join(f"• {d.file_name} ({d.category})" for d in docs)
            if docs
            else "No indexed documents match your criteria."
        )
        sources: list[SourceChunk] = []
        rejected_sources: list[SourceChunk] = []
        retrieved_chunk_ids: list[str] = []
        relevance_scores_list: list[float] = []
        low_confidence = False
    else:
        # ── Hybrid retrieval ──────────────────────────────────────────────────
        result = retrieve(body.query_text, top_k=3, filters=filters)

        langsmith_run_id, langsmith_trace_url = _try_get_langsmith_run()

        # Build selected sources from trace (preserves alignment)
        selected_entries = [e for e in result.trace if e.selected]
        rejected_entries = [e for e in result.trace if not e.selected]

        sources = [
            SourceChunk(
                chunk_id=e.chunk_id,
                file_name=e.file_name,
                page=e.page_number,
                score=round(e.rerank_score, 4),
                text_snippet=e.preview,
                method=e.method,
                chunk_index=e.chunk_index,
                chunk_total=e.chunk_total,
            )
            for e in selected_entries
        ]

        rejected_sources = [
            SourceChunk(
                chunk_id=e.chunk_id,
                file_name=e.file_name,
                page=e.page_number,
                score=round(e.rerank_score, 4),
                text_snippet=e.preview,
                method=e.method,
                chunk_index=e.chunk_index,
                chunk_total=e.chunk_total,
            )
            for e in rejected_entries[:_REJECTED_SOURCES_COUNT]
        ]

        # Aligned lists (same order as selected_entries → sources)
        retrieved_chunk_ids = [e.chunk_id for e in selected_entries]
        relevance_scores_list = [round(e.rerank_score, 4) for e in selected_entries]

        # Persist full trace as serialisable JSON
        retrieval_trace_json = [e.to_dict() for e in result.trace]

        # Low confidence: avg sigmoid-normalised rerank score across selected < threshold
        if not selected_entries:
            low_confidence = True
        else:
            avg_conf = sum(_sigmoid(e.rerank_score) for e in selected_entries) / len(selected_entries)
            low_confidence = avg_conf < _LOW_CONFIDENCE_THRESHOLD

        if not result.chunks:
            answer = (
                "I could not find relevant policy information for your query. "
                "Please try rephrasing or check with your HR team."
            )
        else:
            answer = _build_gpt_answer(body.query_text, sources)

    elapsed_ms = int((time.monotonic() - start_ms) * 1000)

    # ── Persist to query_logs ─────────────────────────────────────────────────
    log = QueryLog(
        user_id=current_user.id,
        query_text=body.query_text,
        retrieved_chunk_ids=retrieved_chunk_ids,
        relevance_scores=relevance_scores_list,
        retrieval_trace=retrieval_trace_json,
        langsmith_run_id=langsmith_run_id,
        langsmith_trace_url=langsmith_trace_url,
        date_filter_from=body.date_from,
        date_filter_to=body.date_to,
        response_latency_ms=elapsed_ms,
    )
    db.add(log)
    db.commit()
    db.refresh(log)

    return QueryResponse(
        answer=answer,
        sources=sources,
        rejected_sources=rejected_sources,
        log_id=log.id,
        low_confidence=low_confidence,
    )


@router.post("/{log_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(
    log_id: uuid.UUID,
    body: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Record thumbs-up / thumbs-down feedback on a previous query."""
    log = db.execute(
        select(QueryLog).where(QueryLog.id == log_id)
    ).scalar_one_or_none()

    if log is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log not found")

    if log.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot update another user's query log",
        )

    db.execute(
        update(QueryLog).where(QueryLog.id == log_id).values(feedback=body.feedback)
    )
    db.commit()
