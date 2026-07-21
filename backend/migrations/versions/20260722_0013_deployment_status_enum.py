"""Align model_deployments.status CHECK constraint with enum definitions.

Revision ID: 20260722_0013
Revises: 20260721_0012
Create Date: 2026-07-22

The status column now accepts ACTIVE, CANARY, SUPERSEDED, and ROLLED_BACK
to match the DeploymentStatus enum in app/application/governance.py and
the DEPLOYMENT_STATUSES frozenset in app/infrastructure/models/enums.py.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260722_0013"
down_revision: str | None = "20260721_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("model_deployments", schema=None) as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=16),
            nullable=False,
            server_default=None,
        )
        batch_op.drop_constraint("status", type_="check")
        batch_op.create_check_constraint(
            "status",
            "status IN ('ACTIVE', 'CANARY', 'SUPERSEDED', 'ROLLED_BACK')",
        )


def downgrade() -> None:
    with op.batch_alter_table("model_deployments", schema=None) as batch_op:
        batch_op.drop_constraint("status", type_="check")
        batch_op.create_check_constraint(
            "status",
            "status IN ('ACTIVE', 'SUPERSEDED', 'FAILED')",
        )
