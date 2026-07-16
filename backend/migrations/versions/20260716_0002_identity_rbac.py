"""Create organization, identity, RBAC, grant, and refresh token tables.

Revision ID: 20260716_0002
Revises: 20260715_0001
Create Date: 2026-07-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "20260716_0002"
down_revision: str | None = "20260715_0001"
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
        "departments",
        uuid_column("id"),
        uuid_column("parent_id", nullable=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("path", sa.String(1024), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        version_column(),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["departments.id"],
            name="fk_departments_parent",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_departments"),
        sa.UniqueConstraint("code", name="uq_departments_code"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name=op.f("ck_departments_status")),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_departments_parent", "departments", ["parent_id"])
    op.create_index("ix_departments_path", "departments", ["path"], mysql_length=191)

    op.create_table(
        "users",
        uuid_column("id"),
        uuid_column("department_id", nullable=True),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("normalized_username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("normalized_email", sa.String(254), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "login_failed_count",
            mysql.SMALLINT(unsigned=True),
            nullable=False,
            server_default="0",
        ),
        sa.Column("locked_until", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("last_login_at", mysql.DATETIME(fsp=6), nullable=True),
        version_column(),
        created_at_column(),
        updated_at_column(),
        sa.Column("deleted_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.ForeignKeyConstraint(
            ["department_id"],
            ["departments.id"],
            name="fk_users_department",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("normalized_username", name="uq_users_username"),
        sa.UniqueConstraint("normalized_email", name="uq_users_email"),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'DISABLED', 'LOCKED')", name=op.f("ck_users_status")
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_users_department_status", "users", ["department_id", "status"])

    op.create_table(
        "roles",
        uuid_column("id"),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column(
            "is_system",
            mysql.TINYINT(display_width=1),
            nullable=False,
            server_default="0",
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        version_column(),
        created_at_column(),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("code", name="uq_roles_code"),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name=op.f("ck_roles_status")),
        sa.CheckConstraint("is_system IN (0, 1)", name=op.f("ck_roles_is_system")),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "permissions",
        uuid_column("id"),
        sa.Column("code", sa.String(128), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("code", name="uq_permissions_code"),
        sa.UniqueConstraint("resource_type", "action", name="uq_permissions_resource_action"),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "user_roles",
        uuid_column("user_id"),
        uuid_column("role_id"),
        uuid_column("granted_by", nullable=True),
        sa.Column(
            "granted_at",
            mysql.DATETIME(fsp=6),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP(6)"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_roles_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="fk_user_roles_role", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"], ["users.id"], name="fk_user_roles_grantor", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("user_id", "role_id", name="pk_user_roles"),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "role_permissions",
        uuid_column("role_id"),
        uuid_column("permission_id"),
        sa.ForeignKeyConstraint(
            ["role_id"],
            ["roles.id"],
            name="fk_role_permissions_role",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="fk_role_permissions_permission",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
        **TABLE_OPTIONS,
    )

    op.create_table(
        "resource_grants",
        uuid_column("id"),
        sa.Column("subject_type", sa.String(16), nullable=False),
        uuid_column("subject_id"),
        sa.Column("resource_type", sa.String(32), nullable=False),
        uuid_column("resource_id"),
        sa.Column("action", sa.String(32), nullable=False),
        created_at_column(),
        updated_at_column(),
        sa.PrimaryKeyConstraint("id", name="pk_resource_grants"),
        sa.UniqueConstraint(
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_resource_grants_subject_resource_action",
        ),
        sa.CheckConstraint(
            "subject_type IN ('USER', 'ROLE')",
            name=op.f("ck_resource_grants_subject_type"),
        ),
        sa.CheckConstraint(
            "resource_type IN ('KNOWLEDGE_BASE', 'MERCHANT', 'REGION')",
            name=op.f("ck_resource_grants_resource_type"),
        ),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_resource_grants_subject", "resource_grants", ["subject_type", "subject_id"])
    op.create_index(
        "ix_resource_grants_resource", "resource_grants", ["resource_type", "resource_id"]
    )

    op.create_table(
        "refresh_tokens",
        uuid_column("id"),
        uuid_column("user_id"),
        sa.Column("token_hash", sa.CHAR(64), nullable=False),
        sa.Column("expires_at", mysql.DATETIME(fsp=6), nullable=False),
        sa.Column("revoked_at", mysql.DATETIME(fsp=6), nullable=True),
        uuid_column("replaced_by_id", nullable=True),
        version_column(),
        created_at_column(),
        updated_at_column(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_refresh_tokens_user", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_id"],
            ["refresh_tokens.id"],
            name="fk_refresh_tokens_replacement",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        **TABLE_OPTIONS,
    )
    op.create_index("ix_refresh_tokens_user_revoked", "refresh_tokens", ["user_id", "revoked_at"])


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_user_revoked", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index("ix_resource_grants_resource", table_name="resource_grants")
    op.drop_index("ix_resource_grants_subject", table_name="resource_grants")
    op.drop_table("resource_grants")
    op.drop_table("role_permissions")
    op.drop_table("user_roles")
    op.drop_table("permissions")
    op.drop_table("roles")
    op.drop_index("ix_users_department_status", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_departments_path", table_name="departments")
    op.drop_index("ix_departments_parent", table_name="departments")
    op.drop_table("departments")
