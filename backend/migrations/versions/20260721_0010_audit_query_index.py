"""Add the result/time audit query index.

Revision ID: 20260721_0010
Revises: 20260721_0009
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0010"
down_revision: str | None = "20260721_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_audit_logs_result_created", "audit_logs", ["result", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_result_created", table_name="audit_logs")
