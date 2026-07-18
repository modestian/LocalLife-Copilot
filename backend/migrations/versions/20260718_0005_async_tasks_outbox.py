"""Create async task and outbox event state tables.

Revision ID: 20260718_0005
Revises: 20260718_0004
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260718_0005"
down_revision: str | None = "20260718_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def datetime_column(
    name: str, *, nullable: bool = True, server_default: sa.TextClause | None = None
) -> sa.Column:
    return sa.Column(name, mysql.DATETIME(fsp=6), nullable=nullable, server_default=server_default)


def upgrade() -> None:
    op.create_table(
        "async_tasks",
        uuid_column("id"),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        uuid_column("resource_id"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("stage", sa.String(20), nullable=False, server_default="QUEUED"),
        sa.Column("progress", mysql.TINYINT(unsigned=True), nullable=False, server_default="0"),
        sa.Column(
            "attempt_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"
        ),
        sa.Column("max_attempts", mysql.INTEGER(unsigned=True), nullable=False, server_default="3"),
        sa.Column("locked_by", sa.String(128), nullable=True),
        datetime_column("locked_until"),
        datetime_column("heartbeat_at"),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("result_json", mysql.JSON(), nullable=True),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        datetime_column(
            "created_at",
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        datetime_column(
            "updated_at",
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_async_tasks"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'CANCEL_REQUESTED', "
            "'SUCCEEDED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_async_tasks_status"),
        ),
        sa.CheckConstraint(
            "stage IN ('QUEUED', 'LOADING', 'CLEANING', 'SPLITTING', "
            "'PERSISTING', 'INDEXING', 'VERIFYING', 'DELETING')",
            name=op.f("ck_async_tasks_stage"),
        ),
        sa.CheckConstraint("progress BETWEEN 0 AND 100", name=op.f("ck_async_tasks_progress")),
        sa.CheckConstraint(
            "status <> 'SUCCEEDED' OR progress = 100",
            name=op.f("ck_async_tasks_success_progress"),
        ),
        sa.CheckConstraint("max_attempts > 0", name=op.f("ck_async_tasks_max_attempts")),
        sa.CheckConstraint(
            "attempt_count <= max_attempts", name=op.f("ck_async_tasks_attempt_count")
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_async_tasks_status_type_created",
        "async_tasks",
        ["status", "task_type", "created_at"],
    )
    op.create_index("ix_async_tasks_locked_until", "async_tasks", ["locked_until"])

    op.create_table(
        "outbox_events",
        uuid_column("event_id"),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        uuid_column("aggregate_id"),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("event_version", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("payload_json", mysql.JSON(), nullable=False),
        datetime_column(
            "occurred_at", nullable=False, server_default=sa.text("CURRENT_TIMESTAMP(6)")
        ),
        datetime_column("published_at"),
        sa.Column(
            "attempt_count", mysql.INTEGER(unsigned=True), nullable=False, server_default="0"
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_by", sa.String(128), nullable=True),
        datetime_column("locked_until"),
        sa.PrimaryKeyConstraint("event_id", name="pk_outbox_events"),
        sa.CheckConstraint("event_version > 0", name=op.f("ck_outbox_events_event_version")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_outbox_unpublished", "outbox_events", ["published_at", "occurred_at"])
    op.create_index("ix_outbox_locked_until", "outbox_events", ["locked_until"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("async_tasks")
