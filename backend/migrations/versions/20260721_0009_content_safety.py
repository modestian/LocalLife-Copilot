"""Create versioned sensitive-word rules and append-only audit logs.

Revision ID: 20260721_0009
Revises: 20260721_0008
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260721_0009"
down_revision: str | None = "20260721_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


def uuid_column(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, mysql.BINARY(16), nullable=nullable)


def timestamp_column(name: str) -> sa.Column:
    return sa.Column(
        name,
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )


def upgrade() -> None:
    op.create_table(
        "sensitive_word_rules",
        uuid_column("id"),
        sa.Column("word", sa.String(200), nullable=False),
        sa.Column("normalized_word", sa.String(200), nullable=False),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("match_type", sa.String(16), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("version_no", mysql.INTEGER(unsigned=True), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="1"),
        uuid_column("created_by"),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_sensitive_word_rules"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_sensitive_rules_creator"),
        sa.UniqueConstraint(
            "normalized_word",
            "scope",
            "version_no",
            name="uq_sensitive_rules_word_scope_version",
        ),
        sa.CheckConstraint("version_no > 0", name="ck_sensitive_word_rules_version_no"),
        sa.CheckConstraint(
            "scope IN ('INPUT', 'OUTPUT', 'BOTH')", name="ck_sensitive_word_rules_scope"
        ),
        sa.CheckConstraint(
            "match_type IN ('CONTAINS', 'EXACT')",
            name="ck_sensitive_word_rules_match_type",
        ),
        sa.CheckConstraint(
            "severity IN ('LOW', 'MEDIUM', 'HIGH')",
            name="ck_sensitive_word_rules_severity",
        ),
        **TABLE_OPTIONS,
    )
    op.create_index(
        "ix_sensitive_rules_enabled_scope", "sensitive_word_rules", ["enabled", "scope"]
    )

    op.create_table(
        "audit_logs",
        uuid_column("id"),
        uuid_column("actor_id"),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        uuid_column("resource_id", nullable=True),
        sa.Column("request_id", sa.String(128), nullable=False),
        sa.Column("ip_address", sa.VARBINARY(16), nullable=True),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("before_summary_json", mysql.JSON(), nullable=True),
        sa.Column("after_summary_json", mysql.JSON(), nullable=True),
        timestamp_column("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name="fk_audit_logs_actor"),
        sa.CheckConstraint(
            "result IN ('SUCCEEDED', 'FAILED', 'BLOCKED')", name="ck_audit_logs_result"
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_id", "created_at"])
    op.create_index(
        "ix_audit_logs_resource_created",
        "audit_logs",
        ["resource_type", "resource_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("sensitive_word_rules")
