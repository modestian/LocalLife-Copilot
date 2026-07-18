"""Add tenant_id column to knowledge_bases table.

The tenant_id field provides an explicit tenant dimension for multi-tenant
isolation, aligning with the OpenSearch mapping that already includes tenant_id.
The existing department_id is retained for organizational hierarchy purposes.

Revision ID: 20260718_0004
Revises: 20260717_0003
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260718_0004"
down_revision: str | None = "20260717_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Add tenant_id column as nullable BINARY(16) foreign key
    op.add_column(
        "knowledge_bases",
        sa.Column("tenant_id", mysql.BINARY(16), nullable=True),
    )
    op.create_foreign_key(
        "fk_kb_tenant",
        "knowledge_bases",
        "departments",
        ["tenant_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # 2. Backfill tenant_id for existing rows where department_id has a value
    op.execute(
        "UPDATE knowledge_bases SET tenant_id = department_id "
        "WHERE tenant_id IS NULL AND department_id IS NOT NULL"
    )

    # 3. Drop the old unique constraint on (department_id, normalized_name, status)
    op.drop_constraint("uq_kb_name_status", "knowledge_bases", type_="unique")

    # 4. Drop the old index on (department_id, status, created_at)
    op.drop_index("ix_kb_department_status", table_name="knowledge_bases")

    # 5. Create new unique constraint on (tenant_id, normalized_name, status)
    op.create_unique_constraint(
        "uq_kb_name_status",
        "knowledge_bases",
        ["tenant_id", "normalized_name", "status"],
    )

    # 6. Create new index on (tenant_id, status, created_at)
    op.create_index(
        "ix_kb_tenant_status",
        "knowledge_bases",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    # 1. Drop the new index
    op.drop_index("ix_kb_tenant_status", table_name="knowledge_bases")

    # 2. Drop the new unique constraint
    op.drop_constraint("uq_kb_name_status", "knowledge_bases", type_="unique")

    # 3. Restore old index on (department_id, status, created_at)
    op.create_index(
        "ix_kb_department_status",
        "knowledge_bases",
        ["department_id", "status", "created_at"],
    )

    # 4. Restore old unique constraint on (department_id, normalized_name, status)
    op.create_unique_constraint(
        "uq_kb_name_status",
        "knowledge_bases",
        ["department_id", "normalized_name", "status"],
    )

    # 5. Drop foreign key and column
    op.drop_constraint("fk_kb_tenant", "knowledge_bases", type_="foreignkey")
    op.drop_column("knowledge_bases", "tenant_id")
