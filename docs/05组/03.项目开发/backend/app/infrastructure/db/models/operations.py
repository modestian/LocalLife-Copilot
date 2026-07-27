"""Persistence models for data sources, merchant master data and LoRA jobs."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CHAR,
    JSON,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary
from app.infrastructure.db.models.identity import (
    DATETIME_6,
    MYSQL_TABLE_OPTIONS,
    TimestampMixin,
    VersionMixin,
)

JSON_TYPE = JSON().with_variant(mysql.JSON(), "mysql")
UNSIGNED_BIGINT = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


class DataSource(TimestampMixin, VersionMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "name", name="uq_data_sources_kb_name"),
        CheckConstraint("source_type IN ('CSV', 'FILE', 'WEB', 'API')", name="source_type"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED', 'DELETED')", name="status"),
        Index("ix_data_sources_kb_status", "knowledge_base_id", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("knowledge_bases.id", name="fk_data_sources_kb"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_data_sources_creator"), nullable=False
    )


class Merchant(TimestampMixin, VersionMixin, Base):
    __tablename__ = "merchants"
    __table_args__ = (
        CheckConstraint("longitude BETWEEN -180 AND 180", name="longitude"),
        CheckConstraint("latitude BETWEEN -90 AND 90", name="latitude"),
        CheckConstraint("avg_price_cent IS NULL OR avg_price_cent >= 0", name="avg_price"),
        CheckConstraint("rating BETWEEN 0 AND 5", name="rating"),
        CheckConstraint(
            "business_status IN ('OPEN', 'CLOSED', 'SUSPENDED', 'UNKNOWN')",
            name="business_status",
        ),
        Index("ix_merchants_category_status", "category", "business_status"),
        Index("ix_merchants_region_status", "region_id", "business_status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    region_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(), ForeignKey("departments.id", name="fk_merchants_region"), nullable=True
    )
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False)
    longitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(10, 7), nullable=False)
    avg_price_cent: Mapped[int | None] = mapped_column(UNSIGNED_BIGINT, nullable=True)
    rating: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=0, server_default="0"
    )
    business_hours_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    business_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)


class Review(TimestampMixin, VersionMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("source_type", "source_review_id", name="uq_reviews_source"),
        CheckConstraint("rating IS NULL OR rating BETWEEN 0 AND 5", name="rating"),
        CheckConstraint("status IN ('PUBLISHED', 'PENDING', 'REJECTED', 'DELETED')", name="status"),
        Index("ix_reviews_merchant_status_date", "merchant_id", "status", "reviewed_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    merchant_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("merchants.id", name="fk_reviews_merchant"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_reviews_user", ondelete="SET NULL"),
        nullable=True,
    )
    author_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)
    reviewed_at: Mapped[datetime] = mapped_column(DATETIME_6, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_review_id: Mapped[str | None] = mapped_column(String(191), nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    tags_json: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)


class MerchantReply(TimestampMixin, Base):
    """商家对点评的回复记录。"""

    __tablename__ = "merchant_replies"
    __table_args__ = (
        CheckConstraint(
            "source IN ('SUGGESTION', 'MANUAL')",
            name="source",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'PUBLISHED', 'REJECTED')",
            name="status",
        ),
        Index("ix_merchant_replies_review", "review_id"),
        Index("ix_merchant_replies_merchant", "merchant_id"),
        Index("ix_merchant_replies_status", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    review_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        nullable=False,
        comment="Logical reference to reviews.id or review_analyses.id",
    )
    merchant_id: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="Matches ReviewAnalysis.merchant_id or merchants.id",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tone: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="MANUAL", server_default="MANUAL"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_merchant_replies_creator"),
        nullable=False,
    )


class FineTuningJob(TimestampMixin, Base):
    __tablename__ = "fine_tuning_jobs"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "base_model_ref", "hyperparameter_hash", name="uq_fine_tuning_job_spec"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name="status",
        ),
        Index("ix_fine_tuning_jobs_status_created", "status", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    dataset_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("datasets.id", name="fk_fine_tuning_jobs_dataset"), nullable=False
    )
    async_task_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("async_tasks.id", name="fk_fine_tuning_jobs_task"),
        nullable=False,
        unique=True,
    )
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    base_model_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    hyperparameters_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    hyperparameter_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    seed: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="PENDING", server_default="PENDING"
    )
    metrics_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    evaluation_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    log_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    artifact_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    artifact_sha256: Mapped[str | None] = mapped_column(CHAR(64), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_fine_tuning_jobs_creator"), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
