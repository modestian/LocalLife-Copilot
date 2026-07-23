from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint
from sqlalchemy.dialects import mysql

from app.core.ids import uuid7
from app.infrastructure.db import Base, UUIDBinary
from app.infrastructure.db.models import (
    Department,
    Permission,
    RefreshToken,
    ResourceGrant,
    Role,
    User,
)


def constraint_names(table: Table, constraint_type: type) -> set[str | None]:
    return {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, constraint_type)
    }


def test_identity_metadata_contains_required_tables() -> None:
    assert set(Base.metadata.tables) == {
        "audit_logs",
        "async_tasks",
        "chunks",
        "conversations",
        "data_sources",
        "dataset_items",
        "datasets",
        "departments",
        "document_versions",
        "documents",
        "feedback",
        "feedback_audits",
        "fine_tuning_jobs",
        "knowledge_bases",
        "message_sources",
        "messages",
        "model_definitions",
        "model_deployments",
        "model_deployment_routes",
        "model_versions",
        "merchants",
        "outbox_events",
        "permissions",
        "prompt_definitions",
        "prompt_versions",
        "refresh_tokens",
        "resource_grants",
        "review_analyses",
        "reviews",
        "role_permissions",
        "roles",
        "sensitive_word_rules",
        "user_roles",
        "users",
    }


def test_uuid_binary_matches_mysql_swap_flag_and_round_trips_uuid7() -> None:
    uuid_type = UUIDBinary()
    dialect = mysql.dialect()
    mysql_example = UUID("6ccd780c-baba-1026-9564-5b8c656024db")
    generated = uuid7()

    assert str(uuid_type.compile(dialect=dialect)) == "BINARY(16)"
    assert uuid_type.process_bind_param(mysql_example, dialect).hex() == (
        "1026baba6ccd780c95645b8c656024db"
    )
    assert (
        uuid_type.process_result_value(bytes.fromhex("1026baba6ccd780c95645b8c656024db"), dialect)
        == mysql_example
    )
    assert (
        uuid_type.process_result_value(uuid_type.process_bind_param(generated, dialect), dialect)
        == generated
    )
    assert uuid_type.process_bind_param(None, dialect) is None
    assert uuid_type.process_result_value(None, dialect) is None


def test_departments_are_hierarchical_versioned_and_indexed() -> None:
    table = Department.__table__
    parent_fk = next(iter(table.foreign_key_constraints))
    path_index = next(index for index in table.indexes if index.name == "ix_departments_path")

    assert "uq_departments_code" in constraint_names(table, UniqueConstraint)
    assert "ck_departments_status" in constraint_names(table, CheckConstraint)
    assert {index.name for index in table.indexes} == {
        "ix_departments_parent",
        "ix_departments_path",
    }
    assert path_index.dialect_options["mysql"]["length"] == 191
    assert parent_fk.name == "fk_departments_parent"
    assert parent_fk.ondelete == "SET NULL"
    assert Department.__mapper__.version_id_col is table.c.version


def test_users_have_documented_constraints_and_department_link() -> None:
    table = User.__table__
    department_fk = next(
        foreign_key
        for foreign_key in table.foreign_key_constraints
        if foreign_key.name == "fk_users_department"
    )

    assert constraint_names(table, UniqueConstraint) >= {
        "uq_users_email",
        "uq_users_username",
    }
    assert "ck_users_status" in constraint_names(table, CheckConstraint)
    assert "ix_users_department_status" in {index.name for index in table.indexes}
    assert department_fk.ondelete == "SET NULL"
    assert User.__mapper__.version_id_col is table.c.version
    assert table.c.deleted_at.nullable is True
    assert table.c.login_failed_count.default.arg == 0


def test_roles_and_permissions_enforce_codes_and_permission_pairs() -> None:
    assert constraint_names(Role.__table__, UniqueConstraint) >= {"uq_roles_code"}
    assert constraint_names(Role.__table__, CheckConstraint) >= {
        "ck_roles_is_system",
        "ck_roles_status",
    }
    assert Role.__mapper__.version_id_col is Role.__table__.c.version
    assert constraint_names(Permission.__table__, UniqueConstraint) >= {
        "uq_permissions_code",
        "uq_permissions_resource_action",
    }


def test_association_foreign_keys_use_documented_delete_rules() -> None:
    user_roles = Base.metadata.tables["user_roles"]
    role_permissions = Base.metadata.tables["role_permissions"]

    assert constraint_names(user_roles, ForeignKeyConstraint) == {
        "fk_user_roles_grantor",
        "fk_user_roles_role",
        "fk_user_roles_user",
    }
    assert constraint_names(role_permissions, ForeignKeyConstraint) == {
        "fk_role_permissions_permission",
        "fk_role_permissions_role",
    }
    assert {foreign_key.ondelete for foreign_key in user_roles.foreign_key_constraints} == {
        "CASCADE",
        "SET NULL",
    }


def test_resource_grant_scope_and_uniqueness_are_constrained() -> None:
    table = ResourceGrant.__table__

    assert "uq_resource_grants_subject_resource_action" in constraint_names(table, UniqueConstraint)
    assert constraint_names(table, CheckConstraint) >= {
        "ck_resource_grants_resource_type",
        "ck_resource_grants_subject_type",
    }
    assert {index.name for index in table.indexes} == {
        "ix_resource_grants_resource",
        "ix_resource_grants_subject",
    }


def test_refresh_token_hash_and_replacement_chain_are_modeled() -> None:
    table = RefreshToken.__table__
    replacement = next(
        foreign_key
        for foreign_key in table.foreign_key_constraints
        if foreign_key.name == "fk_refresh_tokens_replacement"
    )
    user_link = next(
        foreign_key
        for foreign_key in table.foreign_key_constraints
        if foreign_key.name == "fk_refresh_tokens_user"
    )

    assert "uq_refresh_tokens_hash" in constraint_names(table, UniqueConstraint)
    assert table.c.token_hash.type.length == 64
    assert replacement.referred_table is table
    assert replacement.ondelete == "SET NULL"
    assert user_link.ondelete == "CASCADE"
    assert RefreshToken.__mapper__.version_id_col is table.c.version
