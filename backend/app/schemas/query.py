"""Query request/response schemas."""
import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query_text: str = Field(..., min_length=1, max_length=2000)
    date_from: date | None = None
    date_to: date | None = None
    category: str | None = None


class SourceChunk(BaseModel):
    chunk_id: str
    file_name: str
    page: int
    score: float
    text_snippet: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    log_id: uuid.UUID
    low_confidence: bool


class FeedbackRequest(BaseModel):
    feedback: Literal["positive", "negative"]
