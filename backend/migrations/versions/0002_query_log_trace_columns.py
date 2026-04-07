"""Add retrieval_trace, langsmith_run_id, langsmith_trace_url to query_logs

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("query_logs", sa.Column("retrieval_trace", postgresql.JSON, nullable=True))
    op.add_column("query_logs", sa.Column("langsmith_run_id", sa.String(255), nullable=True))
    op.add_column("query_logs", sa.Column("langsmith_trace_url", sa.String(2048), nullable=True))


def downgrade() -> None:
    op.drop_column("query_logs", "langsmith_trace_url")
    op.drop_column("query_logs", "langsmith_run_id")
    op.drop_column("query_logs", "retrieval_trace")
