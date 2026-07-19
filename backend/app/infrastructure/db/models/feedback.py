"""Feedback, dataset and dataset-item persistence models.

Implements the schema defined in docs/project/大众点评AI智能助手-04-数据库约束说明.md
sections 4.4 (feedback) and 4.5/11.8 (datasets).
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
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

UNSIGNED_SMALLINT = SmallInteger().with_variant(mysql.SMALLINT(unsigned=True), "mysql")
UNSIGNED_TINYINT = Integer().with_variant(mysql.TINYINT(unsigned=True), "mysql")
JSON_TYPE = JSON().with_variant(mysql.JSON(), "mysql")
MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


# ---------------------------------------------------------------------------
# Feedback (current effective feedback per user-message pair)
# ---------------------------------------------------------------------------


class Feedback(TimestampMixin, VersionMixin, Base):
    """Current effective feedback for a user-message pair.

    Constraints (04-数据库约束说明.md §4.4):
    - UNIQUE(user_id, message_id): one active feedback per user per message.
    - CHECK rating IN (-1, 1): only thumbs-up or thumbs-down.
    - Updates increment version and write to feedback_audits (application-enforced).
    """

    __tablename__ = "feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
        CheckConstraint("rating IN (-1, 1)", name="rating"),
        Index("ix_feedback_message_rating", "message_id", "rating", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_feedback_user"),
        nullable=False,
    )
    message_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("messages.id", name="fk_feedback_message"),
        nullable=False,
    )
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes_json: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    # PII flag set during redaction scan (TK-501-03)
    pii_flagged: Mapped[bool] = mapped_column(
        UNSIGNED_TINYINT, nullable=False, default=0, server_default="0"
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="PENDING_REVIEW",
        server_default="PENDING_REVIEW",
    )


# ---------------------------------------------------------------------------
# FeedbackAudit (append-only history)
# ---------------------------------------------------------------------------


class FeedbackAudit(Base):
    """Append-only audit trail for feedback version changes.

    Records every version of a feedback entry for traceability during
    dataset generation.  This table must never be UPDATEd or DELETEd
    (application-enforced).
    """

    __tablename__ = "feedback_audits"
    __table_args__ = (
        Index("ix_feedback_audits_feedback_version", "feedback_id", "version_no"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    feedback_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("feedback.id", name="fk_feedback_audits_feedback"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    correction_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    reason_codes_snapshot: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    changed_by: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


# ---------------------------------------------------------------------------
# Dataset (immutable training dataset)
# ---------------------------------------------------------------------------


class Dataset(TimestampMixin, Base):
    """Immutable JSONL training dataset with hash, split config and statistics.

    Constraints (04-数据库约束说明.md §4.5/§11.8):
    - UNIQUE(dataset_hash): content-addressed immutability.
    - CHECK status IN ('BUILDING','READY','REJECTED','ARCHIVED').
    - READY datasets: all content fields immutable (application-enforced).
    """

    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("dataset_hash", name="uq_datasets_hash"),
        CheckConstraint("status IN ('BUILDING', 'READY', 'REJECTED', 'ARCHIVED')", name="status"),
        Index("ix_datasets_status_created", "status", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    filter_config_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    redaction_version: Mapped[str] = mapped_column(String(64), nullable=False)
    split_config_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    sample_count: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    statistics_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="BUILDING",
        server_default="BUILDING",
    )
    # Quality report path and content hash for traceability
    quality_report_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    quality_report_hash: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)


# ---------------------------------------------------------------------------
# DatasetItem (individual sample within a dataset)
# ---------------------------------------------------------------------------


class DatasetItem(Base):
    """Individual sample within a dataset, linked back to source feedback.

    Enables traceability from training data to original conversation/feedback
    and supports train/validation/test split verification.
    """

    __tablename__ = "dataset_items"
    __table_args__ = (
        CheckConstraint("split IN ('train', 'validation', 'test')", name="split"),
        Index("ix_dataset_items_dataset_split", "dataset_id", "split"),
        Index("ix_dataset_items_feedback", "feedback_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    dataset_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("datasets.id", name="fk_dataset_items_dataset"),
        nullable=False,
    )
    feedback_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("feedback.id", name="fk_dataset_items_feedback"),
        nullable=True,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    message_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    user_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    # model_version_id references model_versions which may not exist yet;
    # FK added in a later migration per 04-数据库约束说明.md §11.10
    model_version_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    split: Mapped[str] = mapped_column(String(12), nullable=False)
    # Immutable content snapshot (PII-redacted)
    content_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )
