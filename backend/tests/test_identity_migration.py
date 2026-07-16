import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import sqlalchemy as sa


class RecordingOperations:
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
    path = Path(__file__).parents[1] / "migrations" / "versions" / "20260716_0002_identity_rbac.py"
    spec = importlib.util.spec_from_file_location("identity_rbac_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_items(recorder: RecordingOperations, table_name: str) -> tuple[Any, ...]:
    return next(items for name, items, _ in recorder.created_tables if name == table_name)


def test_upgrade_builds_identity_schema_in_dependency_order() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260716_0002"
    assert migration.down_revision == "20260715_0001"
    assert [name for name, _, _ in recorder.created_tables] == [
        "departments",
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "resource_grants",
        "refresh_tokens",
    ]
    assert {name for name, _, _, _ in recorder.created_indexes} == {
        "ix_departments_parent",
        "ix_departments_path",
        "ix_refresh_tokens_user_revoked",
        "ix_resource_grants_resource",
        "ix_resource_grants_subject",
        "ix_users_department_status",
    }
    assert all(
        options
        == {
            "mysql_engine": "InnoDB",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
        }
        for _, _, options in recorder.created_tables
    )
    path_index = next(
        index for index in recorder.created_indexes if index[0] == "ix_departments_path"
    )
    assert path_index[3] == {"mysql_length": 191}


def test_upgrade_uses_binary_uuid_and_explicit_constraints() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.upgrade()

    users = table_items(recorder, "users")
    user_id = next(item for item in users if isinstance(item, sa.Column) and item.name == "id")
    refresh_tokens = table_items(recorder, "refresh_tokens")
    token_hash = next(
        item for item in refresh_tokens if isinstance(item, sa.Column) and item.name == "token_hash"
    )

    assert str(user_id.type) == "BINARY(16)"
    assert token_hash.type.length == 64
    assert {
        item.name
        for _, items, _ in recorder.created_tables
        for item in items
        if isinstance(item, sa.Constraint)
    } >= {
        "ck_departments_status",
        "ck_resource_grants_resource_type",
        "ck_resource_grants_subject_type",
        "ck_roles_status",
        "ck_users_status",
        "fk_refresh_tokens_replacement",
        "fk_users_department",
        "pk_users",
        "uq_refresh_tokens_hash",
        "uq_users_username",
    }


def test_downgrade_removes_tables_and_owned_indexes_in_reverse_dependency_order() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped_tables == [
        "refresh_tokens",
        "resource_grants",
        "role_permissions",
        "user_roles",
        "permissions",
        "roles",
        "users",
        "departments",
    ]
    assert recorder.dropped_indexes == []
