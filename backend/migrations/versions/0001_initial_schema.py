"""Initial schema — users, policy_documents, query_logs

Revision ID: 0001
Revises:
Create Date: 2026-04-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql  # still needed for UUID and JSON column types
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_enum_if_missing(name: str, *values: str) -> None:
    """PostgreSQL has no CREATE TYPE IF NOT EXISTS — check pg_catalog first."""
    # Inside EXECUTE '...', every literal single-quote must be doubled ('').
    labels_sql = ", ".join(f"''{v}''" for v in values)
    op.execute(
        f"""
        DO $enum$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = '{name}' AND n.nspname = current_schema()
            ) THEN
                EXECUTE 'CREATE TYPE {name} AS ENUM ({labels_sql})';
            END IF;
        END
        $enum$;
        """
    )


def upgrade() -> None:
    # ── Enum types (must exist before tables; create_type=False on columns) ───
    _create_enum_if_missing("userrole", "admin", "user")
    _create_enum_if_missing("userstatus", "active", "suspended")
    _create_enum_if_missing("documentstatus", "queued", "processing", "indexed", "failed")
    _create_enum_if_missing("feedbacktype", "positive", "negative")

    userrole = postgresql.ENUM("admin", "user", name="userrole", create_type=False)
    userstatus = postgresql.ENUM("active", "suspended", name="userstatus", create_type=False)
    documentstatus = postgresql.ENUM(
        "queued", "processing", "indexed", "failed",
        name="documentstatus",
        create_type=False,
    )
    feedbacktype = postgresql.ENUM("positive", "negative", name="feedbacktype", create_type=False)

    # ── users ─────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column(
            "role",
            userrole,
            nullable=False,
            server_default=sa.text("'user'::userrole"),
        ),
        sa.Column(
            "status",
            userstatus,
            nullable=False,
            server_default=sa.text("'active'::userstatus"),
        ),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ── policy_documents ──────────────────────────────────────────────────────
    op.create_table(
        "policy_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("file_name", sa.String(512), nullable=False),
        sa.Column("category", sa.String(255), nullable=False),
        sa.Column("owner_department", sa.String(255), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "status",
            documentstatus,
            nullable=False,
            server_default=sa.text("'queued'::documentstatus"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_policy_documents_file_name", "policy_documents", ["file_name"])
    op.create_index("ix_policy_documents_category", "policy_documents", ["category"])

    # ── query_logs ────────────────────────────────────────────────────────────
    op.create_table(
        "query_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("retrieved_chunk_ids", postgresql.JSON, nullable=True),
        sa.Column("relevance_scores", postgresql.JSON, nullable=True),
        sa.Column("date_filter_from", sa.Date, nullable=True),
        sa.Column("date_filter_to", sa.Date, nullable=True),
        sa.Column(
            "feedback",
            feedbacktype,
            nullable=True,
        ),
        sa.Column("response_latency_ms", sa.Integer, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"])
    op.create_index("ix_query_logs_created_at", "query_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("query_logs")
    op.drop_table("policy_documents")
    op.drop_table("users")

    op.execute("DROP TYPE IF EXISTS feedbacktype")
    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS userstatus")
    op.execute("DROP TYPE IF EXISTS userrole")
