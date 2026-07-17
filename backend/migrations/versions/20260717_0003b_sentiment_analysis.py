"""Create review_analyses table for sentiment analysis result persistence.

Revision ID: 20260717_0003b
Revises: 20260717_0003
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260717_0003b"
down_revision: str | None = "20260717_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )


def updated_at_column() -> sa.Column:
    return sa.Column(
        "updated_at",
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)"),
    )


def version_column() -> sa.Column:
    return sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1")


def upgrade() -> None:
    op.create_table(
        "review_analyses",
        uuid_column("id"),
        sa.Column("merchant_id", sa.String(128), nullable=True),
        sa.Column("review_text", mysql.TEXT(), nullable=False),
        sa.Column("sentiment", sa.String(16), nullable=False),
        sa.Column("confidence", mysql.FLOAT(), nullable=False),
        sa.Column("model_version", sa.String(128), nullable=False),
        sa.Column("aspect_labels", mysql.JSON(), nullable=False),
        sa.Column("negative_reasons", mysql.JSON(), nullable=False),
        sa.Column("review_date", mysql.DATETIME(fsp=6), nullable=True),
        version_column(),
        created_at_column(),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name="pk_review_analyses"),
        sa.CheckConstraint(
            "sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE')",
            name=op.f("ck_review_analyses_sentiment"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_review_analyses_merchant_sentiment", "review_analyses", ["merchant_id", "sentiment"]
    )
    op.create_index("ix_review_analyses_review_date", "review_analyses", ["review_date"])
    op.create_index(
        "ix_review_analyses_sentiment_date", "review_analyses", ["sentiment", "review_date"]
    )


def downgrade() -> None:
    op.drop_table("review_analyses")
