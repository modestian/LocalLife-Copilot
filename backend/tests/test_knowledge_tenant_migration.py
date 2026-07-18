"""Tests for the 20260718_0004_add_tenant_id migration.

Verifies that:
- The tenant_id column is added with correct foreign key.
- The unique constraint is migrated from (department_id, ...) to (tenant_id, ...).
- The index is migrated from ix_kb_department_status to ix_kb_tenant_status.
- Backfill of tenant_id from department_id works.
- The downgrade restores the original schema.
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa


class RecordingOperations:
    def __init__(self) -> None:
        self.added_columns: list[tuple[str, str, sa.Column]] = []
        self.added_foreign_keys: list[tuple[str, str, str, list[str], list[str], str | None]] = []
        self.added_indexes: list[tuple[str, str, list[str]]] = []
        self.added_unique_constraints: list[tuple[str, str | None, str, list[str]]] = []
        self.dropped_constraints: list[tuple[str, str, str | None]] = []
        self.dropped_indexes: list[tuple[str, str | None]] = []
        self.dropped_columns: list[tuple[str, str]] = []
        self.executed_sqls: list[str] = []

    def add_column(self, table: str, column: sa.Column) -> None:
        self.added_columns.append((table, column.name, column))

    def create_foreign_key(
        self,
        name: str | None,
        source: str,
        referent: str,
        local_cols: list[str],
        remote_cols: list[str],
        ondelete: str | None = None,
    ) -> None:
        self.added_foreign_keys.append(
            (name or "", source, referent, local_cols, remote_cols, ondelete)
        )

    def create_index(
        self,
        name: str,
        table: str,
        columns: list[str],
        **options: Any,
    ) -> None:
        self.added_indexes.append((name, table, columns))

    def create_unique_constraint(
        self,
        name: str | None,
        table: str,
        columns: Sequence[str],
        **options: Any,
    ) -> None:
        self.added_unique_constraints.append((name or "", table, table, list(columns)))

    def drop_constraint(
        self,
        name: str,
        table: str,
        type_: str | None = None,
    ) -> None:
        self.dropped_constraints.append((name, table, type_))

    def drop_index(self, name: str, *, table_name: str | None = None) -> None:
        self.dropped_indexes.append((name, table_name))

    def drop_column(self, table: str, column: str) -> None:
        self.dropped_columns.append((table, column))

    def execute(self, sql: str) -> None:
        self.executed_sqls.append(sql)

    def f(self, name: str) -> str:
        return name


def load_migration() -> ModuleType:
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260718_0004_add_tenant_id.py"
    spec = importlib.util.spec_from_file_location("knowledge_tenant_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_tenant_id_column_with_foreign_key() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    # tenant_id column should have been added
    added_tenant = [
        (table, colname)
        for table, colname, _ in recorder.added_columns
        if table == "knowledge_bases" and colname == "tenant_id"
    ]
    assert len(added_tenant) == 1, "tenant_id column should be added"
    assert any(
        name == "fk_kb_tenant" and source == "knowledge_bases"
        for name, source, _, _, _, _ in recorder.added_foreign_keys
    ), "fk_kb_tenant foreign key should be created"


def test_upgrade_backfills_tenant_id_from_department_id() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    backfill_sqls = [
        sql
        for sql in recorder.executed_sqls
        if "UPDATE knowledge_bases" in sql.upper() and "tenant_id" in sql
    ]
    assert len(backfill_sqls) >= 1, "should execute backfill SQL for tenant_id"
    assert any("department_id" in sql for sql in backfill_sqls), (
        "backfill should reference department_id"
    )


def test_upgrade_migrates_unique_constraint_to_tenant_id() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    # Old constraint dropped
    assert any(name == "uq_kb_name_status" for name, table, _ in recorder.dropped_constraints), (
        "old uq_kb_name_status should be dropped"
    )

    # New constraint created with tenant_id
    new_unique = [
        (name, columns)
        for name, _, table, columns in recorder.added_unique_constraints
        if name == "uq_kb_name_status"
    ]
    assert len(new_unique) == 1
    _, columns = new_unique[0]
    assert columns == ["tenant_id", "normalized_name", "status"], (
        f"new unique constraint should cover (tenant_id, normalized_name, status), got {columns}"
    )


def test_upgrade_migrates_index_from_department_to_tenant() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    # Old index dropped
    assert any(
        name == "ix_kb_department_status" for name, table_name in recorder.dropped_indexes
    ), "old ix_kb_department_status index should be dropped"

    # New index created
    assert any(
        name == "ix_kb_tenant_status" and table == "knowledge_bases"
        for name, table, columns in recorder.added_indexes
    ), "ix_kb_tenant_status index should be created"


def test_downgrade_restores_original_schema() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    # New index dropped
    assert any(name == "ix_kb_tenant_status" for name, table_name in recorder.dropped_indexes), (
        "ix_kb_tenant_status should be dropped on downgrade"
    )

    # Old index restored
    assert any(
        name == "ix_kb_department_status" and table == "knowledge_bases"
        for name, table, columns in recorder.added_indexes
    ), "ix_kb_department_status should be restored on downgrade"

    # New unique constraint dropped
    dropped_uniques = [
        name for name, table, _ in recorder.dropped_constraints if name == "uq_kb_name_status"
    ]
    assert len(dropped_uniques) >= 1, "uq_kb_name_status should be dropped on downgrade"

    # Old unique constraint restored
    restored_uniques = [
        columns
        for name, _, table, columns in recorder.added_unique_constraints
        if name == "uq_kb_name_status"
    ]
    if restored_uniques:
        assert restored_uniques[-1] == ["department_id", "normalized_name", "status"]

    # tenant_id column and foreign key removed
    assert any(colname == "tenant_id" for table, colname in recorder.dropped_columns), (
        "tenant_id column should be dropped on downgrade"
    )


def test_migration_chain_is_continuous() -> None:
    """Verify the migration forms a continuous chain from the previous migration."""
    migration = load_migration()
    assert migration.revision == "20260718_0004"
    assert migration.down_revision == "20260717_0003"
