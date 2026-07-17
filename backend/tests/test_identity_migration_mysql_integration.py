import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

IDENTITY_TABLES = {
    "departments",
    "permissions",
    "refresh_tokens",
    "resource_grants",
    "role_permissions",
    "roles",
    "user_roles",
    "users",
}

KNOWLEDGE_METADATA_TABLES = {
    "chunks",
    "document_versions",
    "documents",
    "knowledge_bases",
}


@pytest.mark.skipif(
    not os.getenv("MIGRATION_DATABASE_URL"),
    reason="set MIGRATION_DATABASE_URL to run the MySQL migration round-trip test",
)
def test_mysql_identity_migration_supports_downgrade_and_reupgrade() -> None:
    database_url = os.environ["MIGRATION_DATABASE_URL"]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        command.upgrade(config, "head")
        assert IDENTITY_TABLES <= set(inspect(engine).get_table_names())
        assert KNOWLEDGE_METADATA_TABLES <= set(inspect(engine).get_table_names())

        command.downgrade(config, "20260715_0001")
        table_names = set(inspect(engine).get_table_names())
        assert IDENTITY_TABLES.isdisjoint(table_names)
        assert KNOWLEDGE_METADATA_TABLES.isdisjoint(table_names)

        command.upgrade(config, "head")
        table_names = set(inspect(engine).get_table_names())
        assert IDENTITY_TABLES <= table_names
        assert KNOWLEDGE_METADATA_TABLES <= table_names
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == "20260717_0004"
    finally:
        # Leave the shared CI/local integration database at head even if an assertion fails.
        command.upgrade(config, "head")
        engine.dispose()
