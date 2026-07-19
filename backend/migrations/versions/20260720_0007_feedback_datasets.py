"""Create feedback, feedback_audits, datasets, and dataset_items tables.

Revision ID: 20260720_0007
Revises: 20260719_0006
Create Date: 2026-07-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260720_0007"
down_revision: str | None = "20260719_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def timestamp_column(name: str, *, update: bool = False) -> sa.Column:
    default = "CURRENT_TIMESTAMP(6)"
    if update:
        default += " ON UPDATE CURRENT_TIMESTAMP(6)"
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text(default))


def upgrade() -> None:
    # ------------------------------------------------------------------
    # feedback
    # ------------------------------------------------------------------
    op.create_table(
        "feedback",
        uuid_column("id"),
        uuid_column("user_id"),
        uuid_column("message_id"),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("reason_codes_json", mysql.JSON(), nullable=True),
        sa.Column(
            "pii_flagged",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "review_status",
            sa.String(20),
            nullable=False,
            server_default="PENDING_REVIEW",
        ),
        sa.Column(
            "version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default="1",
        ),
        timestamp_column("created_at"),
        timestamp_column("updated_at", update=True),
        sa.PrimaryKeyConstraint("id", name="pk_feedback"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feedback_user"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], name="fk_feedback_message"),
        sa.UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
        sa.CheckConstraint("rating IN (-1, 1)", name=op.f("ck_feedback_rating")),
        sa.CheckConstraint(
            "review_status IN ('PENDING_REVIEW', 'APPROVED', 'REJECTED', 'FLAGGED')",
            name=op.f("ck_feedback_review_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_feedback_message_rating",
        "feedback",
        ["message_id", "rating", "created_at"],
    )

    # ------------------------------------------------------------------
    # feedback_audits
    # ------------------------------------------------------------------
    op.create_table(
        "feedback_audits",
        uuid_column("id"),
        uuid_column("feedback_id"),
        sa.Column("version_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("correction_snapshot", sa.Text(), nullable=True),
        sa.Column("reason_codes_snapshot", mysql.JSON(), nullable=True),
        uuid_column("changed_by"),
        timestamp_column("changed_at"),
        sa.PrimaryKeyConstraint("id", name="pk_feedback_audits"),
        sa.ForeignKeyConstraint(
            ["feedback_id"], ["feedback.id"], name="fk_feedback_audits_feedback"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_feedback_audits_feedback_version",
        "feedback_audits",
        ["feedback_id", "version_no"],
    )

    # ------------------------------------------------------------------
    # datasets
    # ------------------------------------------------------------------
    op.create_table(
        "datasets",
        uuid_column("id"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("dataset_hash", sa.CHAR(64), nullable=False),
        sa.Column("storage_uri", sa.String(1000), nullable=False),
        sa.Column("filter_config_json", mysql.JSON(), nullable=False),
        sa.Column("redaction_version", sa.String(64), nullable=False),
        sa.Column("split_config_json", mysql.JSON(), nullable=False),
        sa.Column("sample_count", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("statistics_json", mysql.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="BUILDING",
        ),
        sa.Column("quality_report_uri", sa.String(1000), nullable=True),
        sa.Column("quality_report_hash", sa.CHAR(64), nullable=True),
        timestamp_column("created_at"),
        timestamp_column("updated_at", update=True),
        sa.PrimaryKeyConstraint("id", name="pk_datasets"),
        sa.UniqueConstraint("dataset_hash", name="uq_datasets_hash"),
        sa.CheckConstraint(
            "status IN ('BUILDING', 'READY', 'REJECTED', 'ARCHIVED')",
            name=op.f("ck_datasets_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_datasets_status_created",
        "datasets",
        ["status", "created_at"],
    )

    # ------------------------------------------------------------------
    # dataset_items
    # ------------------------------------------------------------------
    op.create_table(
        "dataset_items",
        uuid_column("id"),
        uuid_column("dataset_id"),
        uuid_column("feedback_id", nullable=True),
        uuid_column("conversation_id", nullable=True),
        uuid_column("message_id", nullable=True),
        uuid_column("user_id", nullable=True),
        uuid_column("model_version_id", nullable=True),
        sa.Column("split", sa.String(12), nullable=False),
        sa.Column("content_json", mysql.JSON(), nullable=False),
        sa.Column("content_hash", sa.CHAR(64), nullable=False),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_items"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.id"], name="fk_dataset_items_dataset"),
        sa.ForeignKeyConstraint(["feedback_id"], ["feedback.id"], name="fk_dataset_items_feedback"),
        sa.CheckConstraint(
            "split IN ('train', 'validation', 'test')",
            name=op.f("ck_dataset_items_split"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_dataset_items_dataset_split",
        "dataset_items",
        ["dataset_id", "split"],
    )
    op.create_index(
        "ix_dataset_items_feedback",
        "dataset_items",
        ["feedback_id"],
    )


def downgrade() -> None:
    op.drop_table("dataset_items")
    op.drop_table("datasets")
    op.drop_table("feedback_audits")
    op.drop_table("feedback")
