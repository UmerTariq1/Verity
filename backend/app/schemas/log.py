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


class LogSummary(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    query_text: str
    retrieved_chunk_ids: list[str] | None
    relevance_scores: list[float] | None
    date_filter_from: date | None
    date_filter_to: date | None
    feedback: Literal["positive", "negative"] | None
    response_latency_ms: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LogDetail(LogSummary):
    """Extends LogSummary with live chunk text snippets fetched from Chroma."""
    chunk_snippets: list[LogChunkSnippet]


class LogListResponse(BaseModel):
    items: list[LogSummary]
    total: int
    page: int
    size: int
