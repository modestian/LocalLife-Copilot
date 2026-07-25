"""Bind knowledge tasks to the document version they were created for.

Revision ID: 20260726_0017
Revises: 20260726_0016
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260726_0017"
down_revision: str | None = "20260726_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "async_tasks",
        sa.Column("target_version_no", mysql.INTEGER(unsigned=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_async_tasks_target_version_no"),
        "async_tasks",
        "target_version_no IS NULL OR target_version_no > 0",
    )
    op.create_index(
        "ix_async_tasks_resource_target",
        "async_tasks",
        ["resource_type", "resource_id", "task_type", "target_version_no", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_async_tasks_resource_target", table_name="async_tasks")
    op.drop_constraint(op.f("ck_async_tasks_target_version_no"), "async_tasks", type_="check")
    op.drop_column("async_tasks", "target_version_no")
