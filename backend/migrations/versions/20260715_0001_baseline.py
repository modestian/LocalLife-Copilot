"""Create the baseline migration marker.

Revision ID: 20260715_0001
Revises:
Create Date: 2026-07-15
"""

revision = "20260715_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Reserve the initial schema revision for subsequent domain migrations."""


def downgrade() -> None:
    """The baseline has no schema objects to remove."""
