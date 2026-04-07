"""Document request/response schemas."""
import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class DocumentResponse(BaseModel):
    id: uuid.UUID
    file_name: str
    category: str
    owner_department: str
    effective_date: date
    chunk_count: int
    status: str
    created_at: datetime
    uploaded_by_user_id: uuid.UUID | None

    model_config = {"from_attributes": True}


class DocumentUploadResponse(BaseModel):
    doc_id: uuid.UUID
    status: Literal["queued"]
    message: str


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    total: int
    page: int
    size: int
