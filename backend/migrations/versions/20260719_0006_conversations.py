"""Create conversations, messages, and durable message sources.

Revision ID: 20260719_0006
Revises: 20260718_0005
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260719_0006"
down_revision: str | None = "20260718_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def timestamp_column(name: str, *, update: bool = False) -> sa.Column:
    default = "CURRENT_TIMESTAMP(6)"
    if update:
        default += " ON UPDATE CURRENT_TIMESTAMP(6)"
    return sa.Column(
        name, mysql.DATETIME(fsp=6), nullable=False, server_default=sa.text(default)
    )


def upgrade() -> None:
    op.create_table(
        "conversations",
        uuid_column("id"),
        uuid_column("owner_user_id"),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("memory_backend", sa.String(16), nullable=False, server_default="REDIS"),
        uuid_column("current_branch_message_id", nullable=True),
        sa.Column("settings_json", mysql.JSON(), nullable=False),
        sa.Column("version", mysql.INTEGER(unsigned=True), nullable=False, server_default="1"),
        timestamp_column("created_at"),
        timestamp_column("updated_at", update=True),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.ForeignKeyConstraint(
            ["owner_user_id"], ["users.id"], name="fk_conversations_owner"
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'ARCHIVED', 'DELETED')",
            name=op.f("ck_conversations_status"),
        ),
        sa.CheckConstraint(
            "memory_backend IN ('REDIS', 'MYSQL')",
            name=op.f("ck_conversations_memory_backend"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_conversations_owner",
        "conversations",
        ["owner_user_id", "status", "updated_at"],
    )

    op.create_table(
        "messages",
        uuid_column("id"),
        uuid_column("conversation_id"),
        uuid_column("parent_message_id", nullable=True),
        sa.Column("sequence_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", mysql.MEDIUMTEXT(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        uuid_column("model_version_id", nullable=True),
        sa.Column("prompt_tokens", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("completion_tokens", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("latency_ms", mysql.INTEGER(unsigned=True), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], name="fk_messages_conversation"
        ),
        sa.ForeignKeyConstraint(
            ["parent_message_id"], ["messages.id"], name="fk_messages_parent"
        ),
        sa.UniqueConstraint("conversation_id", "sequence_no", name="uq_messages_sequence"),
        sa.UniqueConstraint("conversation_id", "request_id", name="uq_messages_request"),
        sa.CheckConstraint(
            "role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')",
            name=op.f("ck_messages_role"),
        ),
        sa.CheckConstraint(
            "status IN ('STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED')",
            name=op.f("ck_messages_status"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "message_sources",
        uuid_column("message_id"),
        uuid_column("chunk_id"),
        sa.Column("rank_no", mysql.SMALLINT(unsigned=True), nullable=False),
        sa.Column("score", sa.Numeric(8, 7), nullable=True),
        sa.Column("raw_score", sa.Double(), nullable=True),
        sa.Column("source_location_snapshot", sa.String(1000), nullable=False),
        sa.Column("content_snapshot", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("message_id", "chunk_id", name="pk_message_sources"),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name="fk_message_sources_message", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"], ["chunks.id"], name="fk_message_sources_chunk"
        ),
        sa.UniqueConstraint("message_id", "rank_no", name="uq_message_sources_rank"),
        sa.CheckConstraint("rank_no > 0", name=op.f("ck_message_sources_rank_no")),
        **TABLE_OPTIONS,
    )
    op.create_foreign_key(
        "fk_conversations_branch",
        "conversations",
        "messages",
        ["current_branch_message_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_conversations_branch", "conversations", type_="foreignkey")
    op.drop_table("message_sources")
    op.drop_table("messages")
    op.drop_table("conversations")
