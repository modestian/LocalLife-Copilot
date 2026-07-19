from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from app.application.tasks import TaskStage, TaskStatus
from app.core.ids import uuid7
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent
from app.infrastructure.db.repositories.tasks import (
    SQLAlchemyOutboxRepository,
    SQLAlchemyTaskRepository,
)


class ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class FakeSession:
    def __init__(self, *, scalar: Any = None, rows: list[Any] | None = None) -> None:
        self.scalar_result = scalar
        self.rows = rows or []
        self.statements: list[Any] = []

    async def __aenter__(self) -> "FakeSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> "FakeSession":
        return self

    async def scalar(self, statement: Any) -> Any:
        self.statements.append(statement)
        return self.scalar_result

    async def scalars(self, statement: Any) -> ScalarRows:
        self.statements.append(statement)
        return ScalarRows(self.rows)

    async def flush(self) -> None:
        return None

    def add(self, _: object) -> None:
        return None


class FakeSessionFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self) -> FakeSession:
        return self.session


def task_row(**overrides: Any) -> AsyncTask:
    values: dict[str, Any] = {
        "id": uuid7(),
        "task_type": "INGEST",
        "resource_type": "DOCUMENT",
        "resource_id": uuid7(),
        "status": TaskStatus.PENDING.value,
        "stage": TaskStage.QUEUED.value,
        "progress": 0,
        "attempt_count": 0,
        "max_attempts": 3,
        "locked_by": None,
        "locked_until": None,
        "heartbeat_at": None,
        "error_code": None,
        "error_message": None,
        "result_json": None,
    }
    values.update(overrides)
    return AsyncTask(**values)


@pytest.mark.asyncio
async def test_task_claim_uses_row_lock_and_assigns_lease() -> None:
    row = task_row()
    session = FakeSession(scalar=row)
    repository = SQLAlchemyTaskRepository(FakeSessionFactory(session))  # type: ignore[arg-type]

    claim = await repository.claim(row.id, worker_id="worker-a", lease_seconds=30)

    assert claim is not None
    assert row.status == TaskStatus.RUNNING.value
    assert row.attempt_count == 1
    assert row.locked_by == "worker-a"
    sql = str(session.statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_expired_running_task_can_be_taken_over_by_another_worker() -> None:
    row = task_row(
        status=TaskStatus.RUNNING.value,
        attempt_count=1,
        locked_by="worker-old",
        locked_until=utc_now() - timedelta(seconds=1),
    )
    repository = SQLAlchemyTaskRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession(scalar=row))
    )

    claim = await repository.claim(row.id, worker_id="worker-new")

    assert claim is not None
    assert claim.attempt_count == 2
    assert row.locked_by == "worker-new"


@pytest.mark.asyncio
async def test_expired_worker_cannot_heartbeat_complete_or_cancel() -> None:
    row = task_row(
        status=TaskStatus.RUNNING.value,
        stage=TaskStage.CLEANING.value,
        locked_by="worker-a",
        locked_until=utc_now() - timedelta(seconds=1),
    )
    repository = SQLAlchemyTaskRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession(scalar=row))
    )

    assert not await repository.heartbeat(
        row.id, worker_id="worker-a", stage=TaskStage.SPLITTING, progress=40
    )
    assert not await repository.succeed(row.id, worker_id="worker-a", result={})

    row.status = TaskStatus.CANCEL_REQUESTED.value
    assert not await repository.acknowledge_cancellation(row.id, worker_id="worker-a")


@pytest.mark.asyncio
async def test_task_view_exposes_persisted_progress_and_error() -> None:
    row = task_row(
        status=TaskStatus.FAILED.value,
        stage=TaskStage.INDEXING.value,
        progress=80,
        attempt_count=2,
        error_code="INDEX_FAILED",
        error_message="temporary failure",
    )
    repository = SQLAlchemyTaskRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession(scalar=row))
    )

    view = await repository.get(row.id)

    assert view is not None
    assert view.status is TaskStatus.FAILED
    assert view.progress == 80
    assert view.error_code == "INDEX_FAILED"


@pytest.mark.asyncio
async def test_failed_task_retry_clears_error_and_returns_to_queue() -> None:
    row = task_row(
        status=TaskStatus.FAILED.value,
        stage=TaskStage.INDEXING.value,
        attempt_count=1,
        error_code="INDEX_FAILED",
        error_message="temporary failure",
    )
    repository = SQLAlchemyTaskRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession(scalar=row))
    )

    assert await repository.retry(row.id)
    assert row.status == TaskStatus.PENDING.value
    assert row.stage == TaskStage.QUEUED.value
    assert row.error_code is None
    assert row.error_message is None


@pytest.mark.asyncio
async def test_outbox_claim_uses_skip_locked_and_assigns_publisher_lease() -> None:
    event = OutboxEvent(
        event_id=uuid7(),
        aggregate_type="DOCUMENT",
        aggregate_id=uuid7(),
        event_type="DOCUMENT_INDEX_REQUESTED",
        event_version=1,
        payload_json={"document_version_id": str(uuid7())},
        occurred_at=utc_now(),
        published_at=None,
        attempt_count=0,
        last_error=None,
        locked_by=None,
        locked_until=None,
    )
    session = FakeSession(rows=[event])
    repository = SQLAlchemyOutboxRepository(FakeSessionFactory(session))  # type: ignore[arg-type]

    claims = await repository.claim_batch(publisher_id="publisher-a", lease_seconds=30)

    assert [claim.event_id for claim in claims] == [event.event_id]
    assert event.attempt_count == 1
    assert event.locked_by == "publisher-a"
    sql = str(session.statements[0].compile(dialect=mysql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "outbox_events.published_at IS NULL" in sql
    assert "outbox_events.locked_until IS NULL" in sql


@pytest.mark.asyncio
async def test_outbox_failure_releases_lease_and_success_marks_published() -> None:
    event = OutboxEvent(
        event_id=uuid7(),
        aggregate_type="DOCUMENT",
        aggregate_id=uuid7(),
        event_type="DOCUMENT_INDEX_REQUESTED",
        event_version=1,
        payload_json={},
        occurred_at=utc_now(),
        published_at=None,
        attempt_count=1,
        last_error=None,
        locked_by="publisher-a",
        locked_until=utc_now() + timedelta(seconds=30),
    )
    repository = SQLAlchemyOutboxRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession(scalar=event))
    )

    assert await repository.mark_failed(
        event.event_id, publisher_id="publisher-a", error_message="broker unavailable"
    )
    assert event.last_error == "broker unavailable"
    assert event.locked_by is None

    event.locked_by = "publisher-b"
    event.locked_until = utc_now() + timedelta(seconds=30)
    assert await repository.mark_published(event.event_id, publisher_id="publisher-b")
    assert event.published_at is not None
    assert event.last_error is None


@pytest.mark.asyncio
async def test_published_outbox_events_are_excluded_from_future_claims() -> None:
    session = FakeSession(rows=[])
    repository = SQLAlchemyOutboxRepository(FakeSessionFactory(session))  # type: ignore[arg-type]

    assert await repository.claim_batch(publisher_id="publisher-next") == []

    sql = str(session.statements[0].compile(dialect=mysql.dialect()))
    assert "outbox_events.published_at IS NULL" in sql


@pytest.mark.asyncio
async def test_invalid_lease_lengths_are_rejected() -> None:
    task_repository = SQLAlchemyTaskRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession())
    )
    outbox_repository = SQLAlchemyOutboxRepository(  # type: ignore[arg-type]
        FakeSessionFactory(FakeSession())
    )

    with pytest.raises(ValueError, match="lease_seconds"):
        await task_repository.heartbeat(
            uuid7(),
            worker_id="worker-a",
            stage=TaskStage.LOADING,
            progress=5,
            lease_seconds=0,
        )
    with pytest.raises(ValueError, match="lease_seconds"):
        await outbox_repository.claim_batch(publisher_id="publisher-a", lease_seconds=0)
