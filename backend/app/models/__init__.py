# Import all models here so that:
# 1. Alembic's env.py only needs "from app.models import Base" to get full metadata.
# 2. Any module that does "from app.models import User" works without separate imports.

from app.models.base import Base
from app.models.user import User
from app.models.document import PolicyDocument
from app.models.query_log import QueryLog

__all__ = ["Base", "User", "PolicyDocument", "QueryLog"]
