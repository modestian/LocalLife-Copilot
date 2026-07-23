"""Add persistence required by the missing operational APIs.

Revision ID: 20260723_0014
Revises: 20260722_0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260723_0014"
down_revision: str | None = "20260722_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_ARGS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.BINARY(16), nullable=nullable)


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "data_sources",
        _uuid("id"),
        _uuid("knowledge_base_id"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("config_json", mysql.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        _uuid("created_by"),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"], ["knowledge_bases.id"], name="fk_data_sources_kb"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_data_sources_creator"),
        sa.UniqueConstraint("knowledge_base_id", "name", name="uq_data_sources_kb_name"),
        sa.CheckConstraint(
            "source_type IN ('CSV','FILE','WEB','API')", name="ck_data_sources_source_type"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','DISABLED','DELETED')", name="ck_data_sources_status"
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_index("ix_data_sources_kb_status", "data_sources", ["knowledge_base_id", "status"])

    op.create_table(
        "merchants",
        _uuid("id"),
        _uuid("region_id", nullable=True),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("address", sa.String(500), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 7), nullable=False),
        sa.Column("avg_price_cent", mysql.BIGINT(unsigned=True), nullable=True),
        sa.Column("rating", sa.Numeric(3, 2), nullable=False, server_default="0"),
        sa.Column("business_hours_json", mysql.JSON(), nullable=True),
        sa.Column("business_status", sa.String(16), nullable=False, server_default="UNKNOWN"),
        sa.Column("last_verified_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["region_id"], ["departments.id"], name="fk_merchants_region"),
        sa.CheckConstraint("longitude BETWEEN -180 AND 180", name="ck_merchants_longitude"),
        sa.CheckConstraint("latitude BETWEEN -90 AND 90", name="ck_merchants_latitude"),
        sa.CheckConstraint(
            "avg_price_cent IS NULL OR avg_price_cent >= 0", name="ck_merchants_avg_price"
        ),
        sa.CheckConstraint("rating BETWEEN 0 AND 5", name="ck_merchants_rating"),
        sa.CheckConstraint(
            "business_status IN ('OPEN','CLOSED','SUSPENDED','UNKNOWN')",
            name="ck_merchants_business_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_index("ix_merchants_category_status", "merchants", ["category", "business_status"])
    op.create_index("ix_merchants_region_status", "merchants", ["region_id", "business_status"])

    op.create_table(
        "reviews",
        _uuid("id"),
        _uuid("merchant_id"),
        sa.Column("author_ref", sa.String(128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        sa.Column("rating", sa.Numeric(3, 2), nullable=True),
        sa.Column("reviewed_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_review_id", sa.String(191), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("tags_json", mysql.JSON(), nullable=True),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["merchant_id"], ["merchants.id"], name="fk_reviews_merchant"),
        sa.UniqueConstraint("source_type", "source_review_id", name="uq_reviews_source"),
        sa.CheckConstraint("rating IS NULL OR rating BETWEEN 0 AND 5", name="ck_reviews_rating"),
        sa.CheckConstraint(
            "status IN ('PUBLISHED','PENDING','REJECTED','DELETED')",
            name="ck_reviews_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_index(
        "ix_reviews_merchant_status_date",
        "reviews",
        ["merchant_id", "status", "reviewed_at"],
    )

    op.create_table(
        "fine_tuning_jobs",
        _uuid("id"),
        _uuid("dataset_id"),
        _uuid("async_task_id"),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("base_model_ref", sa.String(500), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("hyperparameters_json", mysql.JSON(), nullable=False),
        sa.Column("hyperparameter_hash", sa.CHAR(64), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("metrics_json", mysql.JSON(), nullable=True),
        sa.Column("evaluation_json", mysql.JSON(), nullable=True),
        sa.Column("log_uri", sa.String(1000), nullable=True),
        sa.Column("artifact_uri", sa.String(1000), nullable=True),
        sa.Column("artifact_sha256", sa.CHAR(64), nullable=True),
        _uuid("created_by"),
        sa.Column("completed_at", mysql.DATETIME(fsp=6), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["datasets.id"], name="fk_fine_tuning_jobs_dataset"
        ),
        sa.ForeignKeyConstraint(
            ["async_task_id"], ["async_tasks.id"], name="fk_fine_tuning_jobs_task"
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_fine_tuning_jobs_creator"),
        sa.UniqueConstraint("async_task_id", name="uq_fine_tuning_jobs_task"),
        sa.UniqueConstraint(
            "dataset_id",
            "base_model_ref",
            "hyperparameter_hash",
            name="uq_fine_tuning_job_spec",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','RUNNING','SUCCEEDED','FAILED','CANCELLED')",
            name="ck_fine_tuning_jobs_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_index(
        "ix_fine_tuning_jobs_status_created", "fine_tuning_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("fine_tuning_jobs")
    op.drop_table("reviews")
    op.drop_table("merchants")
    op.drop_table("data_sources")
