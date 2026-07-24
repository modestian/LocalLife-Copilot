"""Add user_id column to reviews table for user-submitted reviews.

Revision ID: 20260724_0015
Revises: 20260723_0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260724_0015"
down_revision: str | None = "20260723_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("user_id", sa.BINARY(16), nullable=True))
    op.create_foreign_key(
        "fk_reviews_user", "reviews", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_reviews_user_status", "reviews", ["user_id", "status"])


def downgrade() -> None:
    op.drop_constraint("fk_reviews_user", "reviews", type_="foreignkey")
    op.drop_index("ix_reviews_user_status", table_name="reviews")
    op.drop_column("reviews", "user_id")
