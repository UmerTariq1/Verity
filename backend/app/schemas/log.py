"""Query log response schemas."""
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class LogChunkSnippet(BaseModel):
    chunk_id: str
    text_snippet: str
    file_name: str
    page_number: int


class LogReceiptEntry(BaseModel):
    """A single chunk in the retrieval receipt shown in admin Analytics."""
    chunk_id: str
    doc_id: str
    file_name: str
    page_number: int
    preview: str
    confidence_pct: float   # sigmoid-normalised rerank score × 100
    method: str             # "keyword_match" | "semantic_match" | "top_ranked"
    selected: bool


class LogSummary(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    user_name: str | None = None
    user_email: str | None = None
    query_text: str
    retrieved_chunk_ids: list[str] | None
    relevance_scores: list[float] | None
    date_filter_from: date | None
    date_filter_to: date | None
    feedback: Literal["positive", "negative"] | None
    response_latency_ms: int | None
    created_at: datetime
    langsmith_trace_url: str | None = None

    model_config = {"from_attributes": True}


class LogDetail(LogSummary):
    """Extends LogSummary with live chunk text snippets and a structured receipt."""
    chunk_snippets: list[LogChunkSnippet]
    retrieval_receipt: list[LogReceiptEntry]


class LogListResponse(BaseModel):
    items: list[LogSummary]
    total: int
    page: int
    size: int


class UserHistoryResponse(BaseModel):
    items: list[LogSummary]
    total: int
    page: int
    size: int


class LowConfidenceLog(BaseModel):
    """A log entry returned by the low-confidence panel endpoint."""
    id: uuid.UUID
    query_text: str
    avg_confidence_pct: float
    created_at: datetime
    user_name: str | None = None
    langsmith_trace_url: str | None = None
