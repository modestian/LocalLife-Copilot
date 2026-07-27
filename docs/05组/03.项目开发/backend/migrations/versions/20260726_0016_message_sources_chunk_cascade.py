"""Add ON DELETE CASCADE to fk_message_sources_chunk.

The original migration omitted ondelete, causing IntegrityError (1451)
when deleting chunks that are referenced by message_sources.

Revision ID: 20260726_0016
Revises: 20260724_0015
Create Date: 2026-07-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260726_0016"
down_revision: str | None = "20260724_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_message_sources_chunk", "message_sources", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_sources_chunk",
        "message_sources",
        "chunks",
        ["chunk_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_message_sources_chunk", "message_sources", type_="foreignkey")
    op.create_foreign_key(
        "fk_message_sources_chunk",
        "message_sources",
        "chunks",
        ["chunk_id"],
        ["id"],
    )
