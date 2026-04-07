"""System health response schemas."""
from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    total_documents: int
    total_chunks: int
    avg_relevance_score: float | None
    queries_today: int
    index_status: str   # "ready" | "empty" | "building"
    vector_store_type: str
    last_indexed_at: datetime | None


class ActivityEvent(BaseModel):
    event_type: str    # "query" | "ingestion"
    description: str
    created_at: datetime


class ActivityResponse(BaseModel):
    events: list[ActivityEvent]


class ReindexResponse(BaseModel):
    message: str
    documents_queued: int


class DocumentPerformance(BaseModel):
    doc_id: str
    file_name: str
    query_count: int
    avg_confidence_pct: float
