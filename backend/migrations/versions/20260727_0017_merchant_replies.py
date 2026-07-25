"""Add merchant_replies table for store reply functionality.

Revision ID: 20260727_0017
Revises: 20260726_0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260727_0017"
down_revision: str | None = "20260726_0016"
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
        "merchant_replies",
        _uuid("id"),
        _uuid("review_id"),
        sa.Column("merchant_id", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("tone", sa.String(16), nullable=False),
        sa.Column(
            "source", sa.String(16), nullable=False, server_default="MANUAL"
        ),
        _uuid("created_by"),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_merchant_replies_creator"
        ),
        sa.CheckConstraint(
            "source IN ('SUGGESTION','MANUAL')", name="ck_merchant_replies_source"
        ),
        sa.PrimaryKeyConstraint("id"),
        **TABLE_ARGS,
    )
    op.create_index("ix_merchant_replies_review", "merchant_replies", ["review_id"])
    op.create_index("ix_merchant_replies_merchant", "merchant_replies", ["merchant_id"])


def downgrade() -> None:
    op.drop_table("merchant_replies")
