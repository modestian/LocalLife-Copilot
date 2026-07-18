from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, Integer, String, Text, text
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

UNSIGNED_TINYINT = Integer().with_variant(mysql.TINYINT(unsigned=True), "mysql")
JSON_TYPE = mysql.JSON()


class AsyncTask(TimestampMixin, VersionMixin, Base):
    __tablename__ = "async_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'CANCEL_REQUESTED', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint(
            "stage IN ('QUEUED', 'LOADING', 'CLEANING', 'SPLITTING', "
            "'PERSISTING', 'INDEXING', 'VERIFYING', 'DELETING')",
            name="stage",
        ),
        CheckConstraint("progress BETWEEN 0 AND 100", name="progress"),
        CheckConstraint("status <> 'SUCCEEDED' OR progress = 100", name="success_progress"),
        CheckConstraint("max_attempts > 0", name="max_attempts"),
        CheckConstraint("attempt_count <= max_attempts", name="attempt_count"),
        Index("ix_async_tasks_status_type_created", "status", "task_type", "created_at"),
        Index("ix_async_tasks_locked_until", "locked_until"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", server_default="PENDING"
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QUEUED", server_default="QUEUED"
    )
    progress: Mapped[int] = mapped_column(
        UNSIGNED_TINYINT, nullable=False, default=0, server_default="0"
    )
    attempt_count: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER, nullable=False, default=3, server_default="3"
    )
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        CheckConstraint("event_version > 0", name="event_version"),
        Index("ix_outbox_unpublished", "published_at", "occurred_at"),
        Index("ix_outbox_locked_until", "locked_until"),
        MYSQL_TABLE_OPTIONS,
    )

    event_id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_version: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    published_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    attempt_count: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
