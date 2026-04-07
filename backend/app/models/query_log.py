import uuid
from datetime import date, datetime

from sqlalchemy import Enum, Text, String, Integer, Date, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)

    # Stored as JSON lists so the schema stays simple and we avoid storing the
    # AI response text (avoids DB bloat — see BRD §7 "Important Decision")
    retrieved_chunk_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    relevance_scores: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Full pipeline trace: ordered list of dicts (selected + rejected chunks)
    # Each entry: chunk_id, doc_id, file_name, page_number, preview, scores{},
    #             method, selected (bool)
    retrieval_trace: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # LangSmith observability — null when tracing is disabled or not installed
    langsmith_run_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    langsmith_trace_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    date_filter_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_filter_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    feedback: Mapped[str | None] = mapped_column(
        Enum("positive", "negative", name="feedbacktype"),
        nullable=True,
    )
    response_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return f"<QueryLog id={self.id} user_id={self.user_id} created_at={self.created_at}>"
