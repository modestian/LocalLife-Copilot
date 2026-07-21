"""Align model_deployments.status CHECK constraint with enum definitions.

Revision ID: 20260722_0013
Revises: 20260721_0012
Create Date: 2026-07-22

The status column now accepts ACTIVE, CANARY, SUPERSEDED, and ROLLED_BACK
to match the DeploymentStatus enum in app/application/governance.py and
the DEPLOYMENT_STATUSES frozenset in app/infrastructure/models/enums.py.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260722_0013"
down_revision: str | None = "20260721_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Replace the CHECK constraint directly with raw SQL to avoid
    # Alembic batch_alter_table naming-convention issues on MySQL 8.x
    # where the named CHECK constraint is not found during DROP.
    op.execute("ALTER TABLE model_deployments DROP CONSTRAINT ck_model_deployments_status")
    op.execute(
        "ALTER TABLE model_deployments "
        "ADD CONSTRAINT ck_model_deployments_status "
        "CHECK (status IN ('ACTIVE', 'CANARY', 'SUPERSEDED', 'ROLLED_BACK'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE model_deployments DROP CONSTRAINT ck_model_deployments_status")
    op.execute(
        "ALTER TABLE model_deployments "
        "ADD CONSTRAINT ck_model_deployments_status "
        "CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'FAILED'))"
    )
