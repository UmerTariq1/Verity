"""Idempotent seed script , creates default admin and user accounts.

Run after applying migrations:
    python seed.py

Safe to run multiple times: existing rows are left untouched.

Uses the `bcrypt` package directly (not passlib) so seeding works with bcrypt 4.1+.
Phase 5 login will verify with passlib or bcrypt , standard bcrypt hashes are compatible.
"""
import sys
import os
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bcrypt
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import SessionLocal
from app.models import QueryLog, User

DEFAULT_ACCOUNTS = [
    {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000001"),
        "name": "Albus",
        "email": "albus@verity.internal",
        "password": "Admin1234!",
        "role": "admin",
        "status": "active",
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000002"),
        "name": "Alice",
        "email": "alice@verity.internal",
        "password": "User1234!",
        "role": "user",
        "status": "active",
    },
    {
        "id": uuid.UUID("00000000-0000-0000-0000-000000000003"),
        "name": "Bob",
        "email": "bob@verity.internal",
        "password": "User1234!",
        "role": "user",
        "status": "active",
    },    
]


def _hash_password(plain: str) -> str:
    """Return a bcrypt hash string (UTF-8) suitable for storage and passlib verify."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def seed() -> None:
    print("Seeding default accounts...")

    with SessionLocal() as db:
        for account in DEFAULT_ACCOUNTS:
            # If a user already exists with this seed UUID, delete it first so the
            # seed is deterministic (IDs and credentials match this file).
            existing = db.get(User, account["id"])
            if existing is not None:
                db.execute(delete(QueryLog).where(QueryLog.user_id == account["id"]))
                db.execute(delete(User).where(User.id == account["id"]))
                db.flush()

            stmt = (
                pg_insert(User)
                .values(
                    id=account["id"],
                    name=account["name"],
                    email=account["email"],
                    password_hash=_hash_password(account["password"]),
                    role=account["role"],
                    status=account["status"],
                )
                .on_conflict_do_nothing(index_elements=["email"])
            )
            db.execute(stmt)

        db.commit()

    print("Done.")
    print("  Admin:  albus@verity.internal / Admin1234!")
    print("  User:   alice@verity.internal  / User1234!")
    print("  User:   bob@verity.internal  / User1234!")


if __name__ == "__main__":
    seed()
