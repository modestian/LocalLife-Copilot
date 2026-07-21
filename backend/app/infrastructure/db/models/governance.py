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
