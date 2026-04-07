"""Query routes.

POST /api/v1/query                      — hybrid RAG query
POST /api/v1/query/{log_id}/feedback    — thumbs up/down on a previous answer
"""
import asyncio
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
from app.schemas.query import FeedbackRequest, QueryRequest, QueryResponse, SourceChunk

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/query", tags=["query"])

# Confidence threshold: if the top re-ranked chunk's score is below this, we
# surface a low-confidence warning in the UI rather than showing a confident answer.
_LOW_CONFIDENCE_THRESHOLD = 0.0   # cross-encoder logits: negative → low confidence


def _build_gpt_answer(query: str, sources: list[SourceChunk]) -> str:
    """Call GPT-4o and return the answer string.

    Wrapped in a dedicated function so it can be mocked in tests and replaced
    with a streaming variant in a future iteration without touching the route.
    """
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
            "If the answer cannot be determined from the excerpts, say so clearly."
        )
        user_message = f"Context:\n{context}\n\nQuestion: {query}"

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            max_tokens=1024,
        )
        return response.choices[0].message.content or "No answer generated."
    except Exception as exc:
        logger.error("GPT-4o call failed: %s", exc)
        return (
            "I was unable to generate an answer at this time. "
            "Please review the source excerpts below."
        )


@router.post("", response_model=QueryResponse)
def query(
    body: QueryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> QueryResponse:
    """Run the hybrid retrieval pipeline and return a GPT-4o answer with sources."""
    start_ms = time.monotonic()

    # ── Fetch known categories for the router ─────────────────────────────────
    rows = db.execute(
        select(PolicyDocument.category).distinct()
    ).scalars().all()
    known_categories: list[str] = [r for r in rows if r]

    # ── Route the query ───────────────────────────────────────────────────────
    route = route_query(body.query_text, known_categories=known_categories)

    # Merge explicit request filters (body) with router-extracted filters so
    # the caller can always override or augment the heuristic extraction.
    filters = dict(route.filters)
    if body.date_from:
        filters["date_from"] = body.date_from.isoformat()
    if body.date_to:
        filters["date_to"] = body.date_to.isoformat()
    if body.category:
        filters["category"] = body.category

    if route.route == "metadata":
        # Metadata queries return a structured document list, not a RAG answer.
        # Build a simple text answer from the DB result set.
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
        retrieved_chunk_ids: list[str] = []
        relevance_scores_list: list[float] = []
        low_confidence = False
    else:
        # ── Hybrid retrieval ──────────────────────────────────────────────────
        result = retrieve(body.query_text, top_k=5, filters=filters)

        sources = [
            SourceChunk(
                chunk_id=chunk.chunk_id,
                file_name=chunk.file_name,
                page=chunk.page_number,
                score=round(result.reranker_scores.get(chunk.chunk_id, chunk.score), 4),
                text_snippet=chunk.text[:400],
            )
            for chunk in result.chunks
        ]

        retrieved_chunk_ids = [chunk.chunk_id for chunk in result.chunks]
        relevance_scores_list = list(result.reranker_scores.values())

        # Low confidence when: no chunks returned, or top chunk score below threshold
        low_confidence = (
            not result.chunks
            or result.chunks[0].score < _LOW_CONFIDENCE_THRESHOLD
        )

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
