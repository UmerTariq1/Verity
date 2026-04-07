from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models.

    All models import from here so Alembic's env.py only needs to import
    this single Base to discover every table's metadata.
    """
    pass
