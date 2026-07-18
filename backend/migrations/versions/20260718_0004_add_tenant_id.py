"""Add tenant_id column to knowledge_bases table.

The tenant_id field provides an explicit tenant dimension for multi-tenant
isolation, aligning with the OpenSearch mapping that already includes tenant_id.
The existing department_id is retained for organizational hierarchy purposes.

Revision ID: 20260718_0004
Revises: 20260717_0004
Create Date: 2026-07-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260718_0004"
down_revision: str | None = "20260717_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable first so existing rows can be assigned before enforcing isolation.
    op.add_column(
        "knowledge_bases",
        sa.Column("tenant_id", mysql.BINARY(16), nullable=True),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "active_flag",
            mysql.TINYINT(display_width=1),
            sa.Computed("CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END", persisted=True),
            nullable=True,
        ),
    )

    # Prefer the resource department and fall back to the owner's department.
    op.execute(
        "UPDATE knowledge_bases AS kb "
        "JOIN users AS owner ON owner.id = kb.owner_id "
        "SET kb.tenant_id = COALESCE(kb.department_id, owner.department_id) "
        "WHERE kb.tenant_id IS NULL"
    )
    op.alter_column(
        "knowledge_bases",
        "tenant_id",
        existing_type=mysql.BINARY(16),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_kb_tenant",
        "knowledge_bases",
        "departments",
        ["tenant_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("uq_kb_name_status", "knowledge_bases", type_="unique")
    op.drop_index("ix_kb_department_status", table_name="knowledge_bases")
    op.create_unique_constraint(
        "uq_kb_tenant_name_active",
        "knowledge_bases",
        ["tenant_id", "normalized_name", "active_flag"],
    )
    op.create_index(
        "ix_kb_tenant_status",
        "knowledge_bases",
        ["tenant_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_kb_tenant_status", table_name="knowledge_bases")
    op.drop_constraint("uq_kb_tenant_name_active", "knowledge_bases", type_="unique")
    op.create_index(
        "ix_kb_department_status",
        "knowledge_bases",
        ["department_id", "status", "created_at"],
    )

    op.create_unique_constraint(
        "uq_kb_name_status",
        "knowledge_bases",
        ["department_id", "normalized_name", "status"],
    )

    op.drop_constraint("fk_kb_tenant", "knowledge_bases", type_="foreignkey")
    op.drop_column("knowledge_bases", "active_flag")
    op.drop_column("knowledge_bases", "tenant_id")
