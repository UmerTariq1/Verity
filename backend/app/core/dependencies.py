"""Reusable FastAPI dependencies for authentication and authorisation.

Usage in route definitions:
    current_user: User = Depends(get_current_user)   # any authenticated user
    _: User = Depends(require_admin)                  # admin-only routes

Role is verified server-side from the JWT claim , never trusted from the
request body or frontend state.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.database import get_db
from app.models import User

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CREDENTIALS_EXCEPTION = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(_oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate the Bearer JWT and return the corresponding User row.

    Raises HTTP 401 if the token is missing, expired, malformed, or the user
    no longer exists in the database.
    Raises HTTP 403 if the user account is suspended.
    """
    try:
        payload = decode_access_token(token)
        uid: str | None = payload.get("uid")
        if uid is None:
            raise _CREDENTIALS_EXCEPTION
    except JWTError:
        raise _CREDENTIALS_EXCEPTION

    user = db.execute(
        select(User).where(User.id == uid)
    ).scalar_one_or_none()

    if user is None:
        raise _CREDENTIALS_EXCEPTION

    if user.status == "suspended":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is suspended",
        )

    return user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Extend get_current_user , additionally require role == 'admin'.

    Raises HTTP 403 if the authenticated user is not an admin.
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
