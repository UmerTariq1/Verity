"""User management routes (admin only).

GET    /api/v1/users          , paginated list with search/filter
POST   /api/v1/users          , create a new user
PATCH  /api/v1/users/{id}     , update role or status
DELETE /api/v1/users/{id}     , remove user account
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dependencies import require_admin
from app.core.security import hash_password
from app.database import get_db
from app.models import User
from app.schemas.user import (
    UserCreateRequest,
    UserListResponse,
    UserPatchRequest,
    UserResponse,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=UserListResponse)
def list_users(
    search: str = "",
    role: str = "",
    status_filter: str = "",
    page: int = 1,
    size: int = 20,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserListResponse:
    """Return a paginated user list. Supports search by name/email and role/status filters."""
    stmt = select(User)
    if search:
        term = f"%{search}%"
        stmt = stmt.where(
            (User.name.ilike(term)) | (User.email.ilike(term))
        )
    if role:
        stmt = stmt.where(User.role == role)
    if status_filter:
        stmt = stmt.where(User.status == status_filter)

    total = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    items = db.execute(
        stmt.order_by(User.email)
        .offset((page - 1) * size)
        .limit(size)
    ).scalars().all()

    return UserListResponse(
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Create a new user account. Raises 409 if the email is already taken."""
    existing = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Email '{body.email}' is already registered",
        )

    user = User(
        name=body.name,
        email=body.email,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def patch_user(
    user_id: uuid.UUID,
    body: UserPatchRequest,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Update a user's role and/or status. At least one field must be provided."""
    if body.role is None and body.status is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one of: role, status",
        )

    user = db.execute(
        select(User).where(User.id == user_id)
    ).scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.role is not None:
        user.role = body.role
    if body.status is not None:
        user.status = body.status

    db.commit()
    db.refresh(user)

    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: uuid.UUID,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    """Delete a user account. Admins cannot delete their own account."""
    if current_admin.id == user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admins cannot delete their own account",
        )

    user = db.execute(
        select(User).where(User.id == user_id)
    ).scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    db.delete(user)
    db.commit()
