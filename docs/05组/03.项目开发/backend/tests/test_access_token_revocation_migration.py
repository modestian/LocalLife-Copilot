import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


class RecordingOperations:
    def __init__(self) -> None:
        self.added_columns: list[tuple[str, Any]] = []
        self.dropped_columns: list[tuple[str, str]] = []

    def add_column(self, table_name: str, column: Any) -> None:
        self.added_columns.append((table_name, column))

    def drop_column(self, table_name: str, column_name: str) -> None:
        self.dropped_columns.append((table_name, column_name))


def load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260721_0012_access_token_revocation.py"
    )
    spec = importlib.util.spec_from_file_location("access_token_revocation_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_access_token_revocation_migration_round_trip_contract() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()
    assert migration.down_revision == "20260721_0011"
    assert len(recorder.added_columns) == 1
    table_name, column = recorder.added_columns[0]
    assert table_name == "users"
    assert column.name == "access_tokens_valid_after"
    assert column.nullable

    migration.downgrade()
    assert recorder.dropped_columns == [("users", "access_tokens_valid_after")]
