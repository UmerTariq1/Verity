"""Auth request/response schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    name: str
    role: str


class MeResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    status: str
    last_active_at: datetime | None

    model_config = {"from_attributes": True}
