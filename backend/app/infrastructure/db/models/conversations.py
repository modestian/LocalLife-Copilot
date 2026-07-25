from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary, utc_now
from app.infrastructure.db.models.identity import (
    DATETIME_6,
    MYSQL_TABLE_OPTIONS,
    UNSIGNED_INTEGER,
    TimestampMixin,
    VersionMixin,
)

MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
JSON_TYPE = JSON().with_variant(mysql.JSON(), "mysql")
UNSIGNED_SMALLINT = SmallInteger().with_variant(mysql.SMALLINT(unsigned=True), "mysql")


class Conversation(TimestampMixin, VersionMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'ARCHIVED', 'DELETED')", name="status"),
        CheckConstraint("memory_backend IN ('REDIS', 'MYSQL')", name="memory_backend"),
        Index("ix_conversations_owner", "owner_user_id", "status", "updated_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    owner_user_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_conversations_owner"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    memory_backend: Mapped[str] = mapped_column(
        String(16), nullable=False, default="REDIS", server_default="REDIS"
    )
    current_branch_message_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("messages.id", name="fk_conversations_branch", ondelete="SET NULL"),
        nullable=True,
    )
    settings_json: Mapped[dict[str, object]] = mapped_column(
        JSON_TYPE, nullable=False, default=dict
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence_no", name="uq_messages_sequence"),
        UniqueConstraint("conversation_id", "request_id", name="uq_messages_request"),
        CheckConstraint("role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')", name="role"),
        CheckConstraint(
            "status IN ('STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED')", name="status"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    conversation_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("conversations.id", name="fk_messages_conversation"),
        nullable=False,
    )
    parent_message_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(), ForeignKey("messages.id", name="fk_messages_parent"), nullable=True
    )
    sequence_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    model_version_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(UNSIGNED_INTEGER, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(UNSIGNED_INTEGER, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(UNSIGNED_INTEGER, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql"),
        default=utc_now,
        server_default=text("CURRENT_TIMESTAMP(6)"),
    )


class MessageSource(Base):
    __tablename__ = "message_sources"
    __table_args__ = (
        UniqueConstraint("message_id", "rank_no", name="uq_message_sources_rank"),
        CheckConstraint("rank_no > 0", name="rank_no"),
        MYSQL_TABLE_OPTIONS,
    )

    message_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("messages.id", name="fk_message_sources_message", ondelete="CASCADE"),
        primary_key=True,
    )
    chunk_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("chunks.id", name="fk_message_sources_chunk", ondelete="CASCADE"),
        primary_key=True,
    )
    rank_no: Mapped[int] = mapped_column(UNSIGNED_SMALLINT, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(8, 7), nullable=True)
    raw_score: Mapped[float | None] = mapped_column(Double, nullable=True)
    source_location_snapshot: Mapped[str] = mapped_column(String(1000), nullable=False)
    content_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
