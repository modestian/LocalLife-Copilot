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
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260717_0003_knowledge_metadata.py"
    )
    spec = importlib.util.spec_from_file_location("knowledge_metadata_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table_items(recorder: RecordingOperations, table_name: str) -> tuple[Any, ...]:
    return next(items for name, items, _ in recorder.created_tables if name == table_name)


def constraint_names(recorder: RecordingOperations) -> set[str]:
    return {
        item.name
        for _, items, _ in recorder.created_tables
        for item in items
        if isinstance(item, sa.Constraint)
    }


def test_upgrade_builds_knowledge_metadata_schema_in_dependency_order() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.upgrade()

    assert migration.revision == "20260717_0003"
    assert migration.down_revision == "20260716_0002"
    assert [name for name, _, _ in recorder.created_tables] == [
        "knowledge_bases",
        "documents",
        "document_versions",
        "chunks",
    ]
    assert {name for name, _, _, _ in recorder.created_indexes} == {
        "ix_chunks_index_status",
        "ix_documents_kb_status",
        "ix_kb_department_status",
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


def test_upgrade_defines_required_foreign_keys_uniques_and_checks() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.upgrade()

    assert constraint_names(recorder) >= {
        "ck_chunks_index_status",
        "ck_chunks_token_count",
        "ck_doc_version_file_size",
        "ck_doc_version_is_current",
        "ck_doc_version_no",
        "ck_documents_status",
        "ck_kb_chunk_size",
        "ck_kb_overlap",
        "ck_kb_status",
        "fk_chunks_version",
        "fk_doc_versions_document",
        "fk_documents_kb",
        "fk_kb_department",
        "fk_kb_owner",
        "pk_chunks",
        "pk_document_versions",
        "pk_documents",
        "pk_knowledge_bases",
        "uq_chunks_no",
        "uq_chunks_os_id",
        "uq_doc_version",
        "uq_documents_source",
        "uq_kb_name_status",
    }


def test_upgrade_uses_mysql_types_for_document_and_chunk_metadata() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder
    migration.upgrade()

    knowledge_bases = table_items(recorder, "knowledge_bases")
    kb_id = next(
        item for item in knowledge_bases if isinstance(item, sa.Column) and item.name == "id"
    )
    chunks = table_items(recorder, "chunks")
    content = next(
        item for item in chunks if isinstance(item, sa.Column) and item.name == "content"
    )
    metadata_json = next(
        item for item in chunks if isinstance(item, sa.Column) and item.name == "metadata_json"
    )
    opensearch_document_id = next(
        item
        for item in chunks
        if isinstance(item, sa.Column) and item.name == "opensearch_document_id"
    )

    assert str(kb_id.type) == "BINARY(16)"
    assert str(content.type) == "MEDIUMTEXT"
    assert str(metadata_json.type) == "JSON"
    assert opensearch_document_id.type.length == 191


def test_downgrade_removes_tables_and_owned_indexes_in_reverse_dependency_order() -> None:
    migration = load_migration()
    recorder = RecordingOperations()
    migration.op = recorder

    migration.downgrade()

    assert recorder.dropped_tables == [
        "chunks",
        "document_versions",
        "documents",
        "knowledge_bases",
    ]
    assert recorder.dropped_indexes == []
