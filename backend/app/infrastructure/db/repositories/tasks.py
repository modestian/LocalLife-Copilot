from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.tasks import (
    OutboxClaim,
    TaskClaim,
    TaskStage,
    TaskStatus,
    TaskView,
    can_claim,
    can_retry,
    cancellation_target,
    validate_progress,
)
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent


class SQLAlchemyTaskRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        *,
        task_type: str,
        resource_type: str,
        resource_id: UUID,
        max_attempts: int = 3,
    ) -> UUID:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        async with self._session_factory() as session, session.begin():
            row = AsyncTask(
                task_type=_required(task_type, "task_type"),
                resource_type=_required(resource_type, "resource_type"),
                resource_id=resource_id,
                max_attempts=max_attempts,
            )
            session.add(row)
            await session.flush()
            return row.id

    async def get(self, task_id: UUID) -> TaskView | None:
        async with self._session_factory() as session:
            row = await session.scalar(select(AsyncTask).where(AsyncTask.id == task_id))
            return None if row is None else _task_view(row)

    async def claim(
        self, task_id: UUID, *, worker_id: str, lease_seconds: int = 60
    ) -> TaskClaim | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await session.scalar(
                select(AsyncTask).where(AsyncTask.id == task_id).with_for_update()
            )
            if row is None or not can_claim(
                status=TaskStatus(row.status),
                attempt_count=row.attempt_count,
                max_attempts=row.max_attempts,
                locked_until=row.locked_until,
                now=now,
            ):
                return None
            row.status = TaskStatus.RUNNING.value
            row.attempt_count += 1
            row.locked_by = _required(worker_id, "worker_id")
            row.locked_until = now + timedelta(seconds=lease_seconds)
            row.heartbeat_at = now
            row.error_code = None
            row.error_message = None
            await session.flush()
            return TaskClaim(
                id=row.id,
                task_type=row.task_type,
                resource_type=row.resource_type,
                resource_id=row.resource_id,
                attempt_count=row.attempt_count,
                max_attempts=row.max_attempts,
                locked_by=row.locked_by,
                locked_until=row.locked_until,
            )

    async def heartbeat(
        self,
        task_id: UUID,
        *,
        worker_id: str,
        stage: TaskStage,
        progress: int,
        lease_seconds: int = 60,
    ) -> bool:
        _validate_lease(lease_seconds)
        validate_progress(TaskStatus.RUNNING, progress)
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await _locked_task(session, task_id)
            if (
                row is None
                or row.status != TaskStatus.RUNNING.value
                or row.locked_by != worker_id
                or row.locked_until is None
                or row.locked_until <= now
            ):
                return False
            row.stage = stage.value
            row.progress = progress
            row.heartbeat_at = now
            row.locked_until = now + timedelta(seconds=lease_seconds)
            return True

    async def cancellation_requested(self, task_id: UUID, *, worker_id: str) -> bool:
        now = utc_now()
        async with self._session_factory() as session:
            row = await session.scalar(select(AsyncTask).where(AsyncTask.id == task_id))
            return bool(
                row is not None
                and row.status == TaskStatus.CANCEL_REQUESTED.value
                and row.locked_by == worker_id
                and row.locked_until is not None
                and row.locked_until > now
            )

    async def request_cancel(self, task_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await _locked_task(session, task_id)
            if row is None:
                return False
            target = cancellation_target(TaskStatus(row.status), TaskStage(row.stage))
            if target is None:
                return False
            row.status = target.value
            if target is TaskStatus.CANCELLED:
                _release_task(row)
            return True

    async def retry(self, task_id: UUID) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await _locked_task(session, task_id)
            if row is None or not can_retry(
                TaskStatus(row.status), row.attempt_count, row.max_attempts
            ):
                return False
            row.status = TaskStatus.PENDING.value
            row.stage = TaskStage.QUEUED.value
            row.error_code = None
            row.error_message = None
            _release_task(row)
            return True

    async def succeed(
        self, task_id: UUID, *, worker_id: str, result: dict[str, object]
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await _owned_running_task(session, task_id, worker_id)
            if row is None:
                return False
            row.status = TaskStatus.SUCCEEDED.value
            row.progress = 100
            row.result_json = result
            _release_task(row)
            return True

    async def fail(
        self, task_id: UUID, *, worker_id: str, error_code: str, error_message: str
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await _owned_running_task(session, task_id, worker_id)
            if row is None:
                return False
            row.status = TaskStatus.FAILED.value
            row.error_code = _required(error_code, "error_code")
            row.error_message = error_message
            _release_task(row)
            return True

    async def acknowledge_cancellation(self, task_id: UUID, *, worker_id: str) -> bool:
        async with self._session_factory() as session, session.begin():
            row = await _locked_task(session, task_id)
            if (
                row is None
                or row.status != TaskStatus.CANCEL_REQUESTED.value
                or row.locked_by != worker_id
                or row.locked_until is None
                or row.locked_until <= utc_now()
            ):
                return False
            row.status = TaskStatus.CANCELLED.value
            _release_task(row)
            return True


class SQLAlchemyOutboxRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(
        self,
        *,
        aggregate_type: str,
        aggregate_id: UUID,
        event_type: str,
        event_version: int,
        payload: dict[str, object],
        session: AsyncSession | None = None,
    ) -> UUID:
        if event_version <= 0:
            raise ValueError("event_version must be positive")
        row = OutboxEvent(
            aggregate_type=_required(aggregate_type, "aggregate_type"),
            aggregate_id=aggregate_id,
            event_type=_required(event_type, "event_type"),
            event_version=event_version,
            payload_json=payload,
        )
        if session is not None:
            session.add(row)
            await session.flush()
            return row.event_id
        async with self._session_factory() as owned_session, owned_session.begin():
            owned_session.add(row)
            await owned_session.flush()
            return row.event_id

    async def claim_batch(
        self, *, publisher_id: str, limit: int = 100, lease_seconds: int = 60
    ) -> list[OutboxClaim]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        _validate_lease(lease_seconds)
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            rows = (
                await session.scalars(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.published_at.is_(None),
                        (OutboxEvent.locked_until.is_(None) | (OutboxEvent.locked_until <= now)),
                    )
                    .order_by(OutboxEvent.occurred_at, OutboxEvent.event_id)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            for row in rows:
                row.locked_by = _required(publisher_id, "publisher_id")
                row.locked_until = now + timedelta(seconds=lease_seconds)
                row.attempt_count += 1
            return [
                OutboxClaim(
                    event_id=row.event_id,
                    aggregate_type=row.aggregate_type,
                    aggregate_id=row.aggregate_id,
                    event_type=row.event_type,
                    event_version=row.event_version,
                    payload=dict(row.payload_json),
                )
                for row in rows
            ]

    async def mark_published(self, event_id: UUID, *, publisher_id: str) -> bool:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await _locked_event(session, event_id)
            if not _event_lease_owned(row, publisher_id, now):
                return False
            row.published_at = now
            row.last_error = None
            _release_event(row)
            return True

    async def mark_failed(
        self, event_id: UUID, *, publisher_id: str, error_message: str
    ) -> bool:
        now = utc_now()
        async with self._session_factory() as session, session.begin():
            row = await _locked_event(session, event_id)
            if not _event_lease_owned(row, publisher_id, now):
                return False
            row.last_error = error_message[:4000]
            _release_event(row)
            return True


async def _locked_task(session: AsyncSession, task_id: UUID) -> AsyncTask | None:
    return await session.scalar(select(AsyncTask).where(AsyncTask.id == task_id).with_for_update())


async def _owned_running_task(
    session: AsyncSession, task_id: UUID, worker_id: str
) -> AsyncTask | None:
    row = await _locked_task(session, task_id)
    if (
        row is None
        or row.status != TaskStatus.RUNNING.value
        or row.locked_by != worker_id
        or row.locked_until is None
        or row.locked_until <= utc_now()
    ):
        return None
    return row


async def _locked_event(session: AsyncSession, event_id: UUID) -> OutboxEvent | None:
    return await session.scalar(
        select(OutboxEvent).where(OutboxEvent.event_id == event_id).with_for_update()
    )


def _release_task(row: AsyncTask) -> None:
    row.locked_by = None
    row.locked_until = None
    row.heartbeat_at = None


def _release_event(row: OutboxEvent) -> None:
    row.locked_by = None
    row.locked_until = None


def _event_lease_owned(row: OutboxEvent | None, owner: str, now: datetime) -> bool:
    return bool(
        row is not None
        and row.published_at is None
        and row.locked_by == owner
        and row.locked_until is not None
        and row.locked_until > now
    )


def _task_view(row: AsyncTask) -> TaskView:
    return TaskView(
        id=row.id,
        task_type=row.task_type,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        status=TaskStatus(row.status),
        stage=TaskStage(row.stage),
        progress=row.progress,
        attempt_count=row.attempt_count,
        max_attempts=row.max_attempts,
        error_code=row.error_code,
        error_message=row.error_message,
        result=None if row.result_json is None else dict(row.result_json),
    )


def _validate_lease(lease_seconds: int) -> None:
    if lease_seconds <= 0:
        raise ValueError("lease_seconds must be positive")


def _required(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be blank")
    return normalized
