"""User management request/response schemas."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class UserCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=8)
    role: Literal["admin", "user"] = "user"


class UserPatchRequest(BaseModel):
    role: Literal["admin", "user"] | None = None
    status: Literal["active", "suspended"] | None = None


class UserResponse(BaseModel):
    id: uuid.UUID
    name: str
    email: str
    role: str
    status: str
    last_active_at: datetime | None

    model_config = {"from_attributes": True}


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    page: int
    size: int
