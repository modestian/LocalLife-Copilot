import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa


class RecordingOperations:
    def __init__(self) -> None:
        self.tables: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.indexes: list[tuple[str, str, tuple[str, ...]]] = []
        self.dropped: list[str] = []

    def create_table(self, name: str, *items: Any, **options: Any) -> None:
        self.tables.append((name, items, options))

    def create_index(self, name: str, table: str, columns: list[str], **_: Any) -> None:
        self.indexes.append((name, table, tuple(columns)))

    def drop_table(self, name: str) -> None:
        self.dropped.append(name)

    def f(self, name: str) -> str:
        return name


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260718_0005_async_tasks_outbox.py"
    )
    spec = importlib.util.spec_from_file_location("task_outbox_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_task_and_outbox_tables_with_required_indexes() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260718_0005"
    assert migration.down_revision == "20260718_0004"
    assert [name for name, _, _ in recorder.tables] == ["async_tasks", "outbox_events"]
    assert {name for name, _, _ in recorder.indexes} == {
        "ix_async_tasks_locked_until",
        "ix_async_tasks_status_type_created",
        "ix_outbox_locked_until",
        "ix_outbox_unpublished",
    }


def test_upgrade_defines_state_and_retry_constraints() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.upgrade()

    constraints = {
        item.name
        for _, items, _ in recorder.tables
        for item in items
        if isinstance(item, sa.Constraint)
    }
    assert constraints >= {
        "ck_async_tasks_attempt_count",
        "ck_async_tasks_max_attempts",
        "ck_async_tasks_progress",
        "ck_async_tasks_status",
        "ck_async_tasks_stage",
        "ck_async_tasks_success_progress",
        "ck_outbox_events_event_version",
        "pk_async_tasks",
        "pk_outbox_events",
    }


def test_downgrade_drops_tables_in_reverse_dependency_order() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped == ["outbox_events", "async_tasks"]
