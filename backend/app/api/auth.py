"""Authentication routes.

POST /api/v1/auth/login  , exchange credentials for a JWT
GET  /api/v1/auth/me     , return the currently authenticated user's profile
"""
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.schemas.auth import LoginRequest, MeResponse, RegisterRequest, TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Validate credentials and issue a signed JWT."""
    user: User | None = db.execute(
        select(User).where(User.email == body.email)
    ).scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        logger.warning("Auth: failed login attempt email=%s", body.email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended",
        )

    token = create_access_token(
        {"sub": user.email, "role": user.role, "uid": str(user.id)}
    )

    db.execute(
        update(User)
        .where(User.id == user.id)
        .values(last_active_at=datetime.now(timezone.utc))
    )
    db.commit()

    logger.info("Auth: login user_id=%s email=%s role=%s", user.id, user.email, user.role)

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        name=user.name,
        role=user.role,
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Register a new user account (role: user). Raises 409 if email is taken."""
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
        role="user",
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(
        {"sub": user.email, "role": user.role, "uid": str(user.id)}
    )

    logger.info("Auth: register user_id=%s email=%s", user.id, user.email)

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        name=user.name,
        role=user.role,
    )


@router.get("/me", response_model=MeResponse)
def me(current_user: User = Depends(get_current_user)) -> MeResponse:
    """Return the profile of the currently authenticated user."""
    logger.debug("Auth: /me user_id=%s", current_user.id)
    return MeResponse.model_validate(current_user)
