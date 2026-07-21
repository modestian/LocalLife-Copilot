"""Immutable prompt/model versions and append-only deployment records."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary, utc_now
from app.infrastructure.db.models.identity import DATETIME_6, MYSQL_TABLE_OPTIONS, TimestampMixin

JSON_TYPE = JSON().with_variant(mysql.JSON(), "mysql")
MEDIUM_TEXT = Text().with_variant(mysql.MEDIUMTEXT(), "mysql")
UNSIGNED_INTEGER = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")


class PromptDefinition(TimestampMixin, Base):
    __tablename__ = "prompt_definitions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_prompt_definitions_code"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    scene: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)


class PromptVersion(Base):
    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_definition_id", "version_no", name="uq_prompt_versions_definition_version"
        ),
        CheckConstraint("version_no > 0", name="version_no"),
        CheckConstraint("status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')", name="status"),
        CheckConstraint(
            "publication_action IS NULL OR publication_action IN ('PUBLISH', 'ROLLBACK')",
            name="publication_action",
        ),
        CheckConstraint(
            "publication_result IS NULL OR publication_result IN ('SUCCEEDED', 'FAILED')",
            name="publication_result",
        ),
        Index("ix_prompt_versions_definition_status", "prompt_definition_id", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    prompt_definition_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("prompt_definitions.id", name="fk_prompt_versions_definition"),
        nullable=False,
    )
    version_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    content: Mapped[str] = mapped_column(MEDIUM_TEXT, nullable=False)
    variables_json: Mapped[dict[str, object]] = mapped_column(JSON_TYPE, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="DRAFT", server_default="DRAFT"
    )
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_prompt_versions_creator"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )
    published_at: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
    published_by: Mapped[UUID | None] = mapped_column(
        UUIDBinary(),
        ForeignKey("users.id", name="fk_prompt_versions_publisher"),
        nullable=True,
    )
    publication_action: Mapped[str | None] = mapped_column(String(16), nullable=True)
    publication_result: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ModelDefinition(TimestampMixin, Base):
    __tablename__ = "model_definitions"
    __table_args__ = (
        UniqueConstraint("code", name="uq_model_definitions_code"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_definition_id", "version", name="uq_model_versions_definition_version"
        ),
        CheckConstraint(
            "status IN ('REGISTERED', 'EVALUATED', 'APPROVED', 'REJECTED', 'ARCHIVED')",
            name="status",
        ),
        Index("ix_model_versions_definition_status", "model_definition_id", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    model_definition_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("model_definitions.id", name="fk_model_versions_definition"),
        nullable=False,
    )
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    base_model_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    adapter_uri: Mapped[str] = mapped_column(String(1000), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    dimension: Mapped[int | None] = mapped_column(UNSIGNED_INTEGER, nullable=True)
    labels_json: Mapped[list[str] | None] = mapped_column(JSON_TYPE, nullable=True)
    metrics_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="REGISTERED", server_default="REGISTERED"
    )
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_model_versions_creator"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class ModelDeployment(Base):
    """Append-only result of a canary, full release, or rollback operation."""

    __tablename__ = "model_deployments"
    __table_args__ = (
        CheckConstraint("traffic_percent BETWEEN 1 AND 100", name="traffic_percent"),
        CheckConstraint("action IN ('CANARY', 'FULL', 'ROLLBACK')", name="action"),
        CheckConstraint("status IN ('ACTIVE', 'SUPERSEDED', 'FAILED')", name="status"),
        CheckConstraint("result IN ('SUCCEEDED', 'FAILED')", name="result"),
        Index("ix_model_deployments_route_status", "scene", "environment", "status"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    scene: Mapped[str] = mapped_column(String(64), nullable=False)
    environment: Mapped[str] = mapped_column(String(32), nullable=False)
    model_version_id: Mapped[UUID] = mapped_column(
        UUIDBinary(),
        ForeignKey("model_versions.id", name="fk_model_deployments_version"),
        nullable=False,
    )
    traffic_percent: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    deployed_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_model_deployments_actor"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class SensitiveWordRule(Base):
    """A versioned sensitive-word rule; prior versions remain traceable."""

    __tablename__ = "sensitive_word_rules"
    __table_args__ = (
        UniqueConstraint(
            "normalized_word", "scope", "version_no", name="uq_sensitive_rules_word_scope_version"
        ),
        CheckConstraint("version_no > 0", name="version_no"),
        CheckConstraint("scope IN ('INPUT', 'OUTPUT', 'BOTH')", name="scope"),
        CheckConstraint("match_type IN ('CONTAINS', 'EXACT')", name="match_type"),
        CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH')", name="severity"),
        Index("ix_sensitive_rules_enabled_scope", "enabled", "scope"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    word: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_word: Mapped[str] = mapped_column(String(200), nullable=False)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    match_type: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    version_no: Mapped[int] = mapped_column(UNSIGNED_INTEGER, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="1")
    created_by: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_sensitive_rules_creator"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


class AuditLog(Base):
    """Append-only security and business audit event."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("result IN ('SUCCEEDED', 'FAILED', 'BLOCKED')", name="result"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_logs_resource_created", "resource_type", "resource_id", "created_at"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    actor_id: Mapped[UUID] = mapped_column(
        UUIDBinary(), ForeignKey("users.id", name="fk_audit_logs_actor"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(UUIDBinary(), nullable=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    ip_address: Mapped[bytes | None] = mapped_column(LargeBinary(16), nullable=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    before_summary_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    after_summary_json: Mapped[dict[str, object] | None] = mapped_column(JSON_TYPE, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DATETIME_6, nullable=False, default=utc_now, server_default=text("CURRENT_TIMESTAMP(6)")
    )


def _reject_changes(target: object, fields: tuple[str, ...]) -> None:
    state = inspect(target)
    if state.persistent and any(state.attrs[field].history.has_changes() for field in fields):
        raise ValueError("version content is immutable; create a new version instead")


@event.listens_for(PromptVersion, "before_update")
def _protect_prompt_version(mapper: object, connection: object, target: PromptVersion) -> None:
    del mapper, connection
    _reject_changes(
        target,
        (
            "prompt_definition_id",
            "version_no",
            "content",
            "variables_json",
            "content_hash",
            "created_by",
        ),
    )
    state = inspect(target)
    previous_status = state.attrs.status.history.deleted
    if (
        state.persistent
        and previous_status
        and previous_status[0] != "DRAFT"
        and any(
            state.attrs[field].history.has_changes()
            for field in (
                "published_at",
                "published_by",
                "publication_action",
                "publication_result",
            )
        )
    ):
        raise ValueError("prompt publication metadata is immutable")


@event.listens_for(ModelVersion, "before_update")
def _protect_model_version(mapper: object, connection: object, target: ModelVersion) -> None:
    del mapper, connection
    _reject_changes(
        target,
        (
            "model_definition_id",
            "version",
            "base_model_ref",
            "adapter_uri",
            "artifact_sha256",
            "dimension",
            "labels_json",
            "metrics_json",
            "created_by",
        ),
    )


@event.listens_for(SensitiveWordRule, "before_update")
def _protect_sensitive_rule(mapper: object, connection: object, target: SensitiveWordRule) -> None:
    del mapper, connection
    _reject_changes(
        target,
        (
            "word",
            "normalized_word",
            "scope",
            "match_type",
            "severity",
            "version_no",
            "created_by",
        ),
    )


@event.listens_for(AuditLog, "before_update")
@event.listens_for(AuditLog, "before_delete")
def _protect_audit_log(mapper: object, connection: object, target: AuditLog) -> None:
    del mapper, connection, target
    raise ValueError("audit logs are append-only")
