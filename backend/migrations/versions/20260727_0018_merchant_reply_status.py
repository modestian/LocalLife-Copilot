"""Add moderation status to merchant_replies.

Revision ID: 20260727_0018
Revises: 20260727_0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260727_0018"
down_revision: str | None = "20260727_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "merchant_replies",
        sa.Column(
            "status", sa.String(16), nullable=False, server_default="PENDING"
        ),
    )
    # Replies created before moderation existed stay visible
    op.execute("UPDATE merchant_replies SET status = 'PUBLISHED'")
    op.create_check_constraint(
        "ck_merchant_replies_status",
        "merchant_replies",
        "status IN ('PENDING', 'PUBLISHED', 'REJECTED')",
    )
    op.create_index("ix_merchant_replies_status", "merchant_replies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_merchant_replies_status", table_name="merchant_replies")
    op.drop_constraint(
        "ck_merchant_replies_status", "merchant_replies", type_="check"
    )
    op.drop_column("merchant_replies", "status")
