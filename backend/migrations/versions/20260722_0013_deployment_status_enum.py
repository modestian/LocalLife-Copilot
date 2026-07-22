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


def _drop_status_check_constraints() -> None:
    """Drop any CHECK constraint touching the status column.

    MySQL 8.x may auto-generate constraint names when the constraint is
    created inside CREATE TABLE, so the name ``ck_model_deployments_status``
    from migration 20260721_0008 might not match the actual database object.
    Query ``information_schema`` to find the real names and drop them.
    """
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.check_constraints cc
                  ON tc.constraint_name = cc.constraint_name
                  AND tc.table_schema = cc.constraint_schema
            WHERE tc.table_schema = DATABASE()
              AND tc.table_name = 'model_deployments'
              AND tc.constraint_type = 'CHECK'
              AND cc.check_clause LIKE '%status%'
            """
        )
    ).fetchall()
    for (constraint_name,) in rows:
        conn.execute(sa.text(f"ALTER TABLE model_deployments DROP CONSTRAINT `{constraint_name}`"))


def upgrade() -> None:
    _drop_status_check_constraints()
    op.execute(
        "ALTER TABLE model_deployments "
        "ADD CONSTRAINT ck_model_deployments_status "
        "CHECK (status IN ('ACTIVE', 'CANARY', 'SUPERSEDED', 'ROLLED_BACK'))"
    )


def downgrade() -> None:
    _drop_status_check_constraints()
    op.execute(
        "ALTER TABLE model_deployments "
        "ADD CONSTRAINT ck_model_deployments_status "
        "CHECK (status IN ('ACTIVE', 'SUPERSEDED', 'FAILED'))"
    )
