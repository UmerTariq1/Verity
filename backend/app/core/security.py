"""JWT creation/verification and password hashing utilities.

JWT payload claims:
  sub   — user email (string)
  role  — "admin" | "user"
  uid   — user UUID as string
  exp   — expiry timestamp (set automatically by python-jose)

Password hashing uses passlib[bcrypt] which wraps bcrypt with a
safe cost-factor and handles the "$2b$" / "$2a$" prefix normalisation.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ───────────────────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """Return a bcrypt hash of the plain-text password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored bcrypt hash."""
    return _pwd_context.verify(plain, hashed)


# ── JWT helpers ────────────────────────────────────────────────────────────────


def create_access_token(data: dict[str, Any]) -> str:
    """Create a signed JWT with expiry from settings.jwt_expire_minutes."""
    payload = dict(data)
    payload["exp"] = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_expire_minutes
    )
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and verify a JWT.

    Raises:
        jose.JWTError: if the token is invalid, expired, or tampered with.
    """
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
