from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary, utc_now

UNSIGNED_SMALLINT = SmallInteger().with_variant(mysql.SMALLINT(unsigned=True), "mysql")
UNSIGNED_INTEGER = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
DATETIME_6 = DateTime(timezone=False).with_variant(mysql.DATETIME(fsp=6), "mysql")
MYSQL_TABLE_OPTIONS = {
    "mysql_engine": "InnoDB",
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME_6,
        default=utc_now,
        onupdate=utc_now,
        server_default=text("CURRENT_TIMESTAMP(6)"),
        server_onupdate=text("CURRENT_TIMESTAMP(6)"),
    )


class VersionMixin:
    version: Mapped[int] = mapped_column(
        UNSIGNED_INTEGER, nullable=False, default=1, server_default="1"
    )

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, object]:
        return {"version_id_col": cls.version}


class Department(TimestampMixin, VersionMixin, Base):
    __tablename__ = "departments"
    __table_args__ = (
        UniqueConstraint("code", name="uq_departments_code"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status"),
        Index("ix_departments_parent", "parent_id"),
        Index("ix_departments_path", "path", mysql_length=191),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    parent_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("departments.id", name="fk_departments_parent", ondelete="SET NULL"),
        nullable=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    path: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )


class User(TimestampMixin, VersionMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("normalized_username", name="uq_users_username"),
        UniqueConstraint("normalized_email", name="uq_users_email"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED', 'LOCKED')", name="status"),
        Index("ix_users_department_status", "department_id", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    department_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("departments.id", name="fk_users_department", ondelete="SET NULL"),
        nullable=True,
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    normalized_username: Mapped[str] = mapped_column(String(64), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    normalized_email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )
    login_failed_count: Mapped[int] = mapped_column(
        UNSIGNED_SMALLINT, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)


class Role(TimestampMixin, VersionMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("code", name="uq_roles_code"),
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="status"),
        CheckConstraint("is_system IN (0, 1)", name="is_system"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ACTIVE", server_default="ACTIVE"
    )


class Permission(TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_permissions_code"),
        UniqueConstraint("resource_type", "action", name="uq_permissions_resource_action"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)


class UserRole(Base):
    __tablename__ = "user_roles"
    __table_args__ = (MYSQL_TABLE_OPTIONS,)

    user_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_user_roles_user", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("roles.id", name="fk_user_roles_role", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_by: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_user_roles_grantor", ondelete="SET NULL"),
        nullable=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DATETIME_6, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (MYSQL_TABLE_OPTIONS,)

    role_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("roles.id", name="fk_role_permissions_role", ondelete="CASCADE"),
        primary_key=True,
    )
    permission_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("permissions.id", name="fk_role_permissions_permission", ondelete="CASCADE"),
        primary_key=True,
    )


class ResourceGrant(TimestampMixin, Base):
    __tablename__ = "resource_grants"
    __table_args__ = (
        UniqueConstraint(
            "subject_type",
            "subject_id",
            "resource_type",
            "resource_id",
            "action",
            name="uq_resource_grants_subject_resource_action",
        ),
        CheckConstraint("subject_type IN ('USER', 'ROLE')", name="subject_type"),
        CheckConstraint(
            "resource_type IN ('KNOWLEDGE_BASE', 'MERCHANT', 'REGION')",
            name="resource_type",
        ),
        Index("ix_resource_grants_subject", "subject_type", "subject_id"),
        Index("ix_resource_grants_resource", "resource_type", "resource_id"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    subject_type: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(UUIDBinary(), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)


class RefreshToken(TimestampMixin, VersionMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_refresh_tokens_hash"),
        Index("ix_refresh_tokens_user_revoked", "user_id", "revoked_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    user_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_refresh_tokens_user", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DATETIME_6, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    replaced_by_id: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("refresh_tokens.id", name="fk_refresh_tokens_replacement", ondelete="SET NULL"),
        nullable=True,
    )
