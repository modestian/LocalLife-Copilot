from unittest.mock import MagicMock

from app import worker
from app.core.config import Settings
from app.infrastructure.db.repositories.lifecycle import SQLAlchemyLifecycleRepository


def test_sync_database_url_uses_worker_compatible_driver() -> None:
    settings = Settings(mysql_user="worker", mysql_password="secret value", mysql_host="db")

    assert settings.sync_database_url.startswith("mysql+pymysql://worker:secret+value@db:")


def test_default_worker_lazily_wires_sqlalchemy_lifecycle_repository(monkeypatch) -> None:
    engine = MagicMock()
    session_factory = MagicMock()
    configured = MagicMock()
    monkeypatch.setattr(worker, "create_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(worker, "sessionmaker", MagicMock(return_value=session_factory))
    monkeypatch.setattr(worker, "configure_lifecycle_repository", configured)

    worker._configure_default_lifecycle_service()

    worker.create_engine.assert_called_once_with(  # type: ignore[attr-defined]
        worker.settings.sync_database_url, pool_pre_ping=True
    )
    repository = configured.call_args.args[0]
    assert isinstance(repository, SQLAlchemyLifecycleRepository)
