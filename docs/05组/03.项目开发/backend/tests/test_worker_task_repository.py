from unittest.mock import AsyncMock, MagicMock

import pytest

from app import worker
from app.application.tasks import OutboxClaim
from app.core.config import Settings
from app.core.ids import uuid7
from app.infrastructure.db.repositories.lifecycle import SQLAlchemyLifecycleRepository


def test_sync_database_url_uses_worker_compatible_driver() -> None:
    settings = Settings(mysql_user="worker", mysql_password="secret value", mysql_host="db")

    assert settings.sync_database_url.startswith("mysql+pymysql://worker:secret+value@db:")


def test_celery_requeues_tasks_when_worker_process_is_lost() -> None:
    assert worker.celery_app.conf.task_acks_late is True
    assert worker.celery_app.conf.task_reject_on_worker_lost is True
    assert worker.celery_app.conf.worker_prefetch_multiplier == 1


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


@pytest.mark.asyncio
async def test_outbox_publisher_marks_success_and_releases_failures_for_retry(monkeypatch) -> None:
    successful = OutboxClaim(uuid7(), "ASYNC_TASK", uuid7(), "knowledge.ingest", 1, {})
    successful.payload["task_id"] = str(successful.aggregate_id)
    failed = OutboxClaim(uuid7(), "ASYNC_TASK", uuid7(), "knowledge.rebuild", 1, {})
    failed.payload["task_id"] = str(failed.aggregate_id)
    repository = MagicMock()
    repository.claim_batch = AsyncMock(return_value=[successful, failed])
    repository.mark_published = AsyncMock(return_value=True)
    repository.mark_failed = AsyncMock(return_value=True)
    engine = MagicMock()
    engine.dispose = AsyncMock()

    monkeypatch.setattr(worker, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(worker, "async_sessionmaker", MagicMock())
    monkeypatch.setattr(worker, "SQLAlchemyOutboxRepository", MagicMock(return_value=repository))

    def send_task(name: str, *, args: list[str]) -> None:
        if name == "knowledge.rebuild":
            raise ConnectionError("broker unavailable")

    monkeypatch.setattr(worker.celery_app, "send_task", send_task)

    result = await worker._publish_outbox()

    assert result == {"published": 1, "failed": 1}
    repository.mark_published.assert_awaited_once_with(
        successful.event_id, publisher_id="celery-outbox-publisher"
    )
    repository.mark_failed.assert_awaited_once_with(
        failed.event_id,
        publisher_id="celery-outbox-publisher",
        error_message="broker unavailable",
    )
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_task_recovery_delegates_to_repository(monkeypatch) -> None:
    repository = MagicMock()
    repository.recover_stale_knowledge_tasks = AsyncMock(return_value=2)
    engine = MagicMock()
    engine.dispose = AsyncMock()

    monkeypatch.setattr(worker, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(worker, "async_sessionmaker", MagicMock())
    monkeypatch.setattr(worker, "SQLAlchemyTaskRepository", MagicMock(return_value=repository))

    assert await worker._recover_stale_knowledge_tasks() == {"recovered": 2}
    repository.recover_stale_knowledge_tasks.assert_awaited_once()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_operational_task_uses_and_disposes_a_fresh_async_engine(monkeypatch) -> None:
    task_id = uuid7()
    engine = MagicMock()
    engine.dispose = AsyncMock()
    runtime = MagicMock()
    runtime.run_merchant_analysis = AsyncMock(return_value={"status": "SUCCEEDED"})
    session_factory = MagicMock()

    monkeypatch.setattr(worker, "create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr(worker, "async_sessionmaker", MagicMock(return_value=session_factory))
    monkeypatch.setattr(worker, "OperationalTaskRuntime", MagicMock(return_value=runtime))

    result = await worker._run_operational_task(task_id, "run_merchant_analysis")

    assert result == {"status": "SUCCEEDED"}
    worker.create_async_engine.assert_called_once_with(  # type: ignore[attr-defined]
        worker.settings.database_url, pool_pre_ping=True
    )
    runtime.run_merchant_analysis.assert_awaited_once_with(task_id)
    engine.dispose.assert_awaited_once()
