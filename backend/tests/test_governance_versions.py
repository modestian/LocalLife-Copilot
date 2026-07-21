"""TK-103-01 prompt/model version and deployment state-machine tests."""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from sqlalchemy import CheckConstraint, Table, UniqueConstraint
from sqlalchemy.orm import Session, make_transient_to_detached

from app.application.governance import (
    DeploymentAction,
    DeploymentRequest,
    InvalidLifecycleTransition,
    validate_canary_capacity,
    validate_deployable,
    validate_model_transition,
)
from app.core.ids import uuid7
from app.infrastructure.db import Base
from app.infrastructure.db.models import (
    ModelDefinition,
    ModelDeployment,
    ModelVersion,
    PromptDefinition,
    PromptVersion,
)
from app.infrastructure.db.models.governance import (
    _protect_model_version,
    _protect_prompt_version,
)


def _constraint_names(table: Table, kind: type) -> set[str | None]:
    return {constraint.name for constraint in table.constraints if isinstance(constraint, kind)}


def test_governance_tables_are_registered() -> None:
    assert {
        "prompt_definitions",
        "prompt_versions",
        "model_definitions",
        "model_versions",
        "model_deployments",
    } <= set(Base.metadata.tables)


def test_version_identity_is_unique_and_statuses_are_constrained() -> None:
    assert "uq_prompt_versions_definition_version" in _constraint_names(
        PromptVersion.__table__, UniqueConstraint
    )
    assert "uq_model_versions_definition_version" in _constraint_names(
        ModelVersion.__table__, UniqueConstraint
    )
    assert "ck_prompt_versions_status" in _constraint_names(
        PromptVersion.__table__, CheckConstraint
    )
    assert "ck_model_versions_status" in _constraint_names(ModelVersion.__table__, CheckConstraint)


def test_definition_codes_are_unique() -> None:
    assert "uq_prompt_definitions_code" in _constraint_names(
        PromptDefinition.__table__, UniqueConstraint
    )
    assert "uq_model_definitions_code" in _constraint_names(
        ModelDefinition.__table__, UniqueConstraint
    )


def test_deployment_record_contains_actor_version_time_and_result() -> None:
    assert {column.name for column in ModelDeployment.__table__.columns} >= {
        "model_version_id",
        "action",
        "status",
        "result",
        "deployed_by",
        "reason",
        "created_at",
    }
    assert "ck_model_deployments_traffic_percent" in _constraint_names(
        ModelDeployment.__table__, CheckConstraint
    )
    assert "ck_model_deployments_result" in _constraint_names(
        ModelDeployment.__table__, CheckConstraint
    )


def test_prompt_publication_contains_actor_action_time_and_result() -> None:
    assert {column.name for column in PromptVersion.__table__.columns} >= {
        "published_at",
        "published_by",
        "publication_action",
        "publication_result",
    }


def test_model_artifact_identity_is_required() -> None:
    assert ModelVersion.__table__.c.adapter_uri.nullable is False
    assert ModelVersion.__table__.c.artifact_sha256.nullable is False


def test_persisted_prompt_content_cannot_be_changed_in_place() -> None:
    row = PromptVersion(
        id=uuid7(),
        prompt_definition_id=uuid7(),
        version_no=1,
        content="original",
        variables_json={},
        status="PUBLISHED",
        content_hash="a" * 64,
        created_by=uuid7(),
    )
    make_transient_to_detached(row)
    with Session() as session:
        session.add(row)
        row.content = "changed"
        with pytest.raises(ValueError, match="create a new version"):
            _protect_prompt_version(None, None, row)


def test_persisted_model_artifact_cannot_be_changed_in_place() -> None:
    row = ModelVersion(
        id=uuid7(),
        model_definition_id=uuid7(),
        version="v1",
        base_model_ref="base@revision",
        adapter_uri="s3://models/v1",
        artifact_sha256="b" * 64,
        status="APPROVED",
        created_by=uuid7(),
    )
    make_transient_to_detached(row)
    with Session() as session:
        session.add(row)
        row.adapter_uri = "s3://models/replaced"
        with pytest.raises(ValueError, match="create a new version"):
            _protect_model_version(None, None, row)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("REGISTERED", "EVALUATED"),
        ("EVALUATED", "APPROVED"),
        ("EVALUATED", "REJECTED"),
        ("APPROVED", "ARCHIVED"),
    ],
)
def test_model_state_machine_allows_documented_transitions(current: str, target: str) -> None:
    validate_model_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [("REGISTERED", "APPROVED"), ("APPROVED", "REJECTED"), ("ARCHIVED", "APPROVED")],
)
def test_model_state_machine_rejects_skips_and_reactivation(current: str, target: str) -> None:
    with pytest.raises(InvalidLifecycleTransition):
        validate_model_transition(current, target)


def test_only_approved_model_is_deployable() -> None:
    validate_deployable("APPROVED")
    with pytest.raises(InvalidLifecycleTransition):
        validate_deployable("EVALUATED")


def test_canary_traffic_cannot_exceed_one_hundred_percent() -> None:
    validate_canary_capacity(70, 30)
    with pytest.raises(InvalidLifecycleTransition):
        validate_canary_capacity(70, 31)


def test_deployment_request_selects_canary_or_full_action() -> None:
    canary = DeploymentRequest(uuid7(), "chat", "prod", 10, uuid7(), "observe metrics")
    full = DeploymentRequest(uuid7(), "chat", "prod", 100, uuid7(), "promote")
    canary.validate()
    full.validate()
    assert canary.action is DeploymentAction.CANARY
    assert full.action is DeploymentAction.FULL


class RecordingOperations:
    def __init__(self) -> None:
        self.created_tables: list[str] = []
        self.created_indexes: list[str] = []
        self.dropped_tables: list[str] = []

    def create_table(self, name: str, *items: Any, **options: Any) -> None:
        del items, options
        self.created_tables.append(name)

    def create_index(self, name: str, table: str, columns: list[str], **options: Any) -> None:
        del table, columns, options
        self.created_indexes.append(name)

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)


def _load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260721_0008_governance_versions.py"
    )
    spec = importlib.util.spec_from_file_location("governance_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_builds_tables_in_dependency_order_without_privileged_ddl() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.upgrade()

    assert migration.down_revision == "20260720_0007"
    assert recorder.created_tables == [
        "prompt_definitions",
        "prompt_versions",
        "model_definitions",
        "model_versions",
        "model_deployments",
    ]


def test_migration_downgrade_removes_tables_in_reverse_dependency_order() -> None:
    migration = _load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.downgrade()
    assert recorder.dropped_tables == [
        "model_deployments",
        "model_versions",
        "model_definitions",
        "prompt_versions",
        "prompt_definitions",
    ]
