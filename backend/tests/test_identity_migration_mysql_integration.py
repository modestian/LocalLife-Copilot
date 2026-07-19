import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.infrastructure.db import Base
from app.infrastructure.db import models as db_models  # noqa: F401

EXPECTED_TABLES = set(Base.metadata.tables)


@pytest.mark.skipif(
    not os.getenv("MIGRATION_DATABASE_URL"),
    reason="set MIGRATION_DATABASE_URL to run the MySQL migration round-trip test",
)
def test_mysql_identity_migration_supports_downgrade_and_reupgrade() -> None:
    database_url = os.environ["MIGRATION_DATABASE_URL"]
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    expected_revision = ScriptDirectory.from_config(config).get_current_head()
    assert expected_revision is not None
    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        command.upgrade(config, "head")
        assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())

        command.downgrade(config, "20260715_0001")
        table_names = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES.isdisjoint(table_names)

        command.upgrade(config, "head")
        table_names = set(inspect(engine).get_table_names())
        assert EXPECTED_TABLES <= table_names
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert revision == expected_revision
    finally:
        # Leave the shared CI/local integration database at head even if an assertion fails.
        command.upgrade(config, "head")
        engine.dispose()
