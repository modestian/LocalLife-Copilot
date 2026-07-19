"""Tests for feedback, dataset and dataset-item ORM models, migration and DTOs.

Covers TK-501-01 acceptance criteria from 06-人员分工任务分配.md:
- feedback UNIQUE(user_id, message_id) idempotency
- rating CHECK IN (-1, 1)
- dataset_hash UNIQUE immutability
- dataset status CHECK (BUILDING/READY/REJECTED/ARCHIVED)
- dataset_item split CHECK (train/validation/test)
- authorization rule constants
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from app.core.ids import uuid7
from app.domain.feedback import (
    DATASET_CREATE_PERMISSION,
    DATASET_READ_PERMISSION,
    DATASET_SPLITS,
    DATASET_STATUSES,
    FEEDBACK_PERMISSION,
    FEEDBACK_READ_PERMISSION,
    FEEDBACK_REVIEW_STATUSES,
    DatasetCreateRequest,
    DatasetFilter,
    FeedbackCreate,
    SplitConfig,
)
from app.infrastructure.db import Base
from app.infrastructure.db.models import Dataset, DatasetItem, Feedback, FeedbackAudit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def constraint_names(table: Table, constraint_type: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type)
    }


class RecordingOperations:
    """Mock Alembic op to record DDL operations without a database."""

    def __init__(self) -> None:
        self.created_tables: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.created_indexes: list[tuple[str, str, tuple[str, ...], dict[str, Any]]] = []
        self.dropped_tables: list[str] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []

    def create_table(self, name: str, *items: Any, **options: Any) -> None:
        self.created_tables.append((name, items, options))

    def create_index(self, name: str, table: str, columns: list[str], **options: Any) -> None:
        self.created_indexes.append((name, table, tuple(columns), options))

    def drop_table(self, name: str) -> None:
        self.dropped_tables.append(name)

    def drop_index(self, name: str, *, table_name: str | None = None) -> None:
        self.dropped_indexes.append((name, table_name))

    def f(self, name: str) -> str:
        return name


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1] / "migrations" / "versions" / "20260720_0007_feedback_datasets.py"
    )
    spec = importlib.util.spec_from_file_location("feedback_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_items(recorder: RecordingOperations, table_name: str) -> tuple[Any, ...]:
    return next(items for name, items, _ in recorder.created_tables if name == table_name)


# ---------------------------------------------------------------------------
# ORM metadata tests
# ---------------------------------------------------------------------------


class TestFeedbackMetadata:
    """Verify Feedback ORM model matches 04-数据库约束说明.md §4.4/§11.7."""

    def test_feedback_table_registered(self) -> None:
        assert "feedback" in Base.metadata.tables

    def test_feedback_unique_user_message(self) -> None:
        table = Feedback.__table__
        assert "uq_feedback_user_message" in constraint_names(table, UniqueConstraint)

    def test_feedback_rating_check_constraint(self) -> None:
        table = Feedback.__table__
        # naming convention: ck_%(table_name)s_%(constraint_name)s
        assert "ck_feedback_rating" in constraint_names(table, CheckConstraint)

    def test_feedback_version_id_column(self) -> None:
        assert Feedback.__mapper__.version_id_col is Feedback.__table__.c.version

    def test_feedback_foreign_keys(self) -> None:
        table = Feedback.__table__
        fk_names = constraint_names(table, ForeignKeyConstraint)
        assert "fk_feedback_user" in fk_names
        assert "fk_feedback_message" in fk_names

    def test_feedback_columns_present(self) -> None:
        columns = {c.name for c in Feedback.__table__.columns}
        assert columns >= {
            "id",
            "user_id",
            "message_id",
            "rating",
            "correction",
            "reason_codes_json",
            "pii_flagged",
            "review_status",
            "version",
            "created_at",
            "updated_at",
        }

    def test_feedback_index_exists(self) -> None:
        index_names = {i.name for i in Feedback.__table__.indexes}
        assert "ix_feedback_message_rating" in index_names

    def test_feedback_review_status_defaults_to_pending(self) -> None:
        col = Feedback.__table__.c.review_status
        assert col.server_default is not None
        assert col.default is not None


class TestFeedbackAuditMetadata:
    """Verify FeedbackAudit is append-only (no update/delete mixin)."""

    def test_feedback_audits_table_registered(self) -> None:
        assert "feedback_audits" in Base.metadata.tables

    def test_feedback_audit_no_timestamp_mixin(self) -> None:
        columns = {c.name for c in FeedbackAudit.__table__.columns}
        assert "updated_at" not in columns
        assert "version" not in columns

    def test_feedback_audit_no_version_id(self) -> None:
        assert getattr(FeedbackAudit.__mapper__, "version_id_col", None) is None

    def test_feedback_audit_foreign_key(self) -> None:
        table = FeedbackAudit.__table__
        fk_names = constraint_names(table, ForeignKeyConstraint)
        assert "fk_feedback_audits_feedback" in fk_names

    def test_feedback_audit_index(self) -> None:
        index_names = {i.name for i in FeedbackAudit.__table__.indexes}
        assert "ix_feedback_audits_feedback_version" in index_names

    def test_feedback_audit_columns(self) -> None:
        columns = {c.name for c in FeedbackAudit.__table__.columns}
        assert columns >= {
            "id",
            "feedback_id",
            "version_no",
            "rating",
            "correction_snapshot",
            "reason_codes_snapshot",
            "changed_by",
            "changed_at",
        }


class TestDatasetMetadata:
    """Verify Dataset ORM model matches 04-数据库约束说明.md §4.5/§11.8."""

    def test_datasets_table_registered(self) -> None:
        assert "datasets" in Base.metadata.tables

    def test_dataset_hash_unique(self) -> None:
        table = Dataset.__table__
        assert "uq_datasets_hash" in constraint_names(table, UniqueConstraint)

    def test_dataset_status_check_constraint(self) -> None:
        table = Dataset.__table__
        # naming convention: ck_%(table_name)s_%(constraint_name)s
        assert "ck_datasets_status" in constraint_names(table, CheckConstraint)

    def test_dataset_no_version_mixin(self) -> None:
        """Datasets are immutable once READY; no optimistic-locking version column."""
        columns = {c.name for c in Dataset.__table__.columns}
        assert "version" not in columns

    def test_dataset_columns_match_doc_spec(self) -> None:
        columns = {c.name for c in Dataset.__table__.columns}
        assert columns >= {
            "id",
            "name",
            "task_type",
            "dataset_hash",
            "storage_uri",
            "filter_config_json",
            "redaction_version",
            "split_config_json",
            "sample_count",
            "statistics_json",
            "status",
            "quality_report_uri",
            "quality_report_hash",
            "created_at",
            "updated_at",
        }

    def test_dataset_index_exists(self) -> None:
        index_names = {i.name for i in Dataset.__table__.indexes}
        assert "ix_datasets_status_created" in index_names

    def test_dataset_status_defaults_to_building(self) -> None:
        col = Dataset.__table__.c.status
        assert col.server_default is not None
        assert col.default is not None


class TestDatasetItemMetadata:
    """Verify DatasetItem ORM model matches 04-数据库约束说明.md §11.8."""

    def test_dataset_items_table_registered(self) -> None:
        assert "dataset_items" in Base.metadata.tables

    def test_dataset_item_split_check_constraint(self) -> None:
        table = DatasetItem.__table__
        # naming convention: ck_%(table_name)s_%(constraint_name)s
        assert "ck_dataset_items_split" in constraint_names(table, CheckConstraint)

    def test_dataset_item_foreign_keys(self) -> None:
        table = DatasetItem.__table__
        fk_names = constraint_names(table, ForeignKeyConstraint)
        assert "fk_dataset_items_dataset" in fk_names
        assert "fk_dataset_items_feedback" in fk_names

    def test_dataset_item_indexes(self) -> None:
        index_names = {i.name for i in DatasetItem.__table__.indexes}
        assert "ix_dataset_items_dataset_split" in index_names
        assert "ix_dataset_items_feedback" in index_names

    def test_dataset_item_optional_feedback_id(self) -> None:
        col = DatasetItem.__table__.c.feedback_id
        assert col.nullable is True

    def test_dataset_item_columns(self) -> None:
        columns = {c.name for c in DatasetItem.__table__.columns}
        assert columns >= {
            "id",
            "dataset_id",
            "feedback_id",
            "conversation_id",
            "message_id",
            "user_id",
            "model_version_id",
            "split",
            "content_json",
            "content_hash",
            "created_at",
        }


# ---------------------------------------------------------------------------
# Migration tests
# ---------------------------------------------------------------------------


class TestMigrationUpgrade:
    """Verify Alembic migration creates tables in dependency order."""

    def test_revision_chain(self) -> None:
        migration = load_migration()
        assert migration.revision == "20260720_0007"
        assert migration.down_revision == "20260719_0006"

    def test_upgrade_creates_tables_in_dependency_order(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.upgrade()

        assert [name for name, _, _ in recorder.created_tables] == [
            "feedback",
            "feedback_audits",
            "datasets",
            "dataset_items",
        ]

    def test_upgrade_uses_mysql_table_options(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.upgrade()

        assert all(
            options
            == {
                "mysql_engine": "InnoDB",
                "mysql_charset": "utf8mb4",
                "mysql_collate": "utf8mb4_0900_ai_ci",
            }
            for _, _, options in recorder.created_tables
        )

    def test_upgrade_creates_expected_indexes(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.upgrade()

        assert {name for name, _, _, _ in recorder.created_indexes} == {
            "ix_feedback_message_rating",
            "ix_feedback_audits_feedback_version",
            "ix_datasets_status_created",
            "ix_dataset_items_dataset_split",
            "ix_dataset_items_feedback",
        }

    def test_upgrade_defines_explicit_constraints(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.upgrade()

        constraint_names_found: set[str | None] = set()
        for _, items, _ in recorder.created_tables:
            for item in items:
                if isinstance(item, Any.__class__):
                    pass
            for item in items:
                if hasattr(item, "name") and hasattr(item, "__class__"):
                    cls_name = type(item).__name__
                    if cls_name in (
                        "PrimaryKeyConstraint",
                        "UniqueConstraint",
                        "CheckConstraint",
                        "ForeignKeyConstraint",
                    ):
                        constraint_names_found.add(item.name)

        assert constraint_names_found >= {
            "pk_feedback",
            "uq_feedback_user_message",
            "fk_feedback_user",
            "fk_feedback_message",
            "pk_feedback_audits",
            "fk_feedback_audits_feedback",
            "pk_datasets",
            "uq_datasets_hash",
            "pk_dataset_items",
            "fk_dataset_items_dataset",
            "fk_dataset_items_feedback",
        }


class TestMigrationDowngrade:
    """Verify Alembic migration drops tables in reverse dependency order."""

    def test_downgrade_drops_tables_in_reverse_order(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.downgrade()

        assert recorder.dropped_tables == [
            "dataset_items",
            "datasets",
            "feedback_audits",
            "feedback",
        ]

    def test_downgrade_drops_no_explicit_indexes(self) -> None:
        migration = load_migration()
        recorder = RecordingOperations()
        migration.op = recorder

        migration.downgrade()

        # MySQL drops indexes implicitly when their table is dropped
        assert recorder.dropped_indexes == []


# ---------------------------------------------------------------------------
# DTO Schema validation tests
# ---------------------------------------------------------------------------


class TestFeedbackCreateSchema:
    """Verify FeedbackCreate DTO enforces 03-API接口规范.md §8.1 rules."""

    def _valid_payload(self) -> dict[str, Any]:
        return {
            "conversation_id": str(uuid7()),
            "message_id": str(uuid7()),
            "rating": 1,
        }

    def test_valid_positive_rating(self) -> None:
        payload = self._valid_payload()
        dto = FeedbackCreate(**payload)
        assert dto.rating == 1

    def test_valid_negative_rating(self) -> None:
        payload = self._valid_payload()
        payload["rating"] = -1
        dto = FeedbackCreate(**payload)
        assert dto.rating == -1

    def test_zero_rating_rejected(self) -> None:
        payload = self._valid_payload()
        payload["rating"] = 0
        with pytest.raises(ValidationError):
            FeedbackCreate(**payload)

    def test_rating_outside_allowed_values(self) -> None:
        payload = self._valid_payload()
        payload["rating"] = 2
        with pytest.raises(ValidationError):
            FeedbackCreate(**payload)

    def test_correction_max_4000_chars(self) -> None:
        payload = self._valid_payload()
        payload["correction"] = "x" * 4000
        dto = FeedbackCreate(**payload)
        assert len(dto.correction) == 4000

    def test_correction_over_4000_chars_rejected(self) -> None:
        payload = self._valid_payload()
        payload["correction"] = "x" * 4001
        with pytest.raises(ValidationError):
            FeedbackCreate(**payload)

    def test_reason_codes_default_empty(self) -> None:
        dto = FeedbackCreate(**self._valid_payload())
        assert dto.reason_codes == []

    def test_required_fields_missing(self) -> None:
        with pytest.raises(ValidationError):
            FeedbackCreate(rating=1)  # type: ignore[call-arg]


class TestSplitConfigSchema:
    """Verify SplitConfig DTO enforces split ratio ranges."""

    def test_default_config(self) -> None:
        config = SplitConfig()
        assert config.isolation_key == "CONVERSATION"
        assert config.train_percent == 0.8
        assert config.validation_percent == 0.1
        assert config.test_percent == 0.1
        assert config.random_seed == 42

    def test_custom_config(self) -> None:
        config = SplitConfig(
            isolation_key="ENTITY",
            train_percent=0.7,
            validation_percent=0.2,
            test_percent=0.1,
            random_seed=123,
        )
        assert config.isolation_key == "ENTITY"

    def test_train_percent_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SplitConfig(train_percent=1.5)

    def test_negative_random_seed_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SplitConfig(random_seed=-1)

    def test_invalid_isolation_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SplitConfig(isolation_key="INVALID")  # type: ignore[arg-type]


class TestDatasetCreateRequestSchema:
    """Verify DatasetCreateRequest DTO field constraints."""

    def test_valid_request(self) -> None:
        req = DatasetCreateRequest(name="test-dataset", task_type="sentiment")
        assert req.name == "test-dataset"
        assert req.task_type == "sentiment"
        assert isinstance(req.filter, DatasetFilter)
        assert isinstance(req.split_config, SplitConfig)

    def test_name_max_200_chars(self) -> None:
        DatasetCreateRequest(name="x" * 200, task_type="t")

    def test_name_over_200_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DatasetCreateRequest(name="x" * 201, task_type="t")

    def test_task_type_max_64_chars(self) -> None:
        DatasetCreateRequest(name="n", task_type="x" * 64)

    def test_task_type_over_64_chars_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DatasetCreateRequest(name="n", task_type="x" * 65)


class TestDatasetFilterSchema:
    """Verify DatasetFilter supports ST-501 criterion ③ filtering."""

    def test_empty_filter_allows_all(self) -> None:
        f = DatasetFilter()
        assert f.rating is None
        assert f.task_type is None
        assert f.review_status is None
        assert f.start_date is None
        assert f.end_date is None

    def test_rating_filter_positive(self) -> None:
        f = DatasetFilter(rating=1)
        assert f.rating == 1

    def test_rating_filter_negative(self) -> None:
        f = DatasetFilter(rating=-1)
        assert f.rating == -1

    def test_rating_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            DatasetFilter(rating=0)


# ---------------------------------------------------------------------------
# Authorization constant tests
# ---------------------------------------------------------------------------


class TestAuthorizationConstants:
    """Verify permission and status constants match documentation."""

    def test_feedback_permission_is_rbac_code(self) -> None:
        assert FEEDBACK_PERMISSION == "feedback.create"

    def test_feedback_read_permission(self) -> None:
        assert FEEDBACK_READ_PERMISSION == "feedback.read"

    def test_dataset_create_permission(self) -> None:
        assert DATASET_CREATE_PERMISSION == "feedback.dataset.create"

    def test_dataset_read_permission(self) -> None:
        assert DATASET_READ_PERMISSION == "feedback.dataset.read"

    def test_dataset_statuses_match_doc(self) -> None:
        assert DATASET_STATUSES == frozenset({"BUILDING", "READY", "REJECTED", "ARCHIVED"})

    def test_feedback_review_statuses(self) -> None:
        assert FEEDBACK_REVIEW_STATUSES == frozenset({"PENDING_REVIEW", "APPROVED", "REJECTED"})

    def test_dataset_splits(self) -> None:
        assert DATASET_SPLITS == frozenset({"train", "validation", "test"})
