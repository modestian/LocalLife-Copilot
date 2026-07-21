"""Serialize model releases by scene and environment.

Revision ID: 20260721_0011
Revises: 20260721_0010
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260721_0011"
down_revision: str | None = "20260721_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def upgrade() -> None:
    op.create_table(
        "model_deployment_routes",
        sa.Column("id", mysql.BINARY(16), nullable=False),
        sa.Column("scene", sa.String(64), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.PrimaryKeyConstraint("id", name="pk_model_deployment_routes"),
        sa.UniqueConstraint("scene", "environment", name="uq_model_deployment_routes_key"),
        **TABLE_OPTIONS,
    )


def downgrade() -> None:
    op.drop_table("model_deployment_routes")
