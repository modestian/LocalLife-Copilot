from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TaskStage(StrEnum):
    QUEUED = "QUEUED"
    LOADING = "LOADING"
    CLEANING = "CLEANING"
    SPLITTING = "SPLITTING"
    PERSISTING = "PERSISTING"
    INDEXING = "INDEXING"
    VERIFYING = "VERIFYING"
    DELETING = "DELETING"


TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED})
NON_INTERRUPTIBLE_STAGES = frozenset(
    {TaskStage.PERSISTING, TaskStage.INDEXING, TaskStage.VERIFYING, TaskStage.DELETING}
)


class InvalidTaskTransition(ValueError):
    """The requested state change violates the persisted task state machine."""


@dataclass(frozen=True, slots=True)
class TaskClaim:
    id: UUID
    task_type: str
    resource_type: str
    resource_id: UUID
    attempt_count: int
    max_attempts: int
    locked_by: str
    locked_until: datetime


@dataclass(frozen=True, slots=True)
class TaskView:
    id: UUID
    task_type: str
    resource_type: str
    resource_id: UUID
    status: TaskStatus
    stage: TaskStage
    progress: int
    attempt_count: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    result: dict[str, object] | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class OutboxClaim:
    event_id: UUID
    aggregate_type: str
    aggregate_id: UUID
    event_type: str
    event_version: int
    payload: dict[str, object]


def cancellation_target(status: TaskStatus, stage: TaskStage) -> TaskStatus | None:
    if status is TaskStatus.PENDING:
        return TaskStatus.CANCELLED
    if status is TaskStatus.RUNNING and stage not in NON_INTERRUPTIBLE_STAGES:
        return TaskStatus.CANCEL_REQUESTED
    return None


def validate_progress(status: TaskStatus, progress: int) -> None:
    if not 0 <= progress <= 100:
        raise ValueError("progress must be between 0 and 100")
    if status is TaskStatus.SUCCEEDED and progress != 100:
        raise InvalidTaskTransition("succeeded tasks must have 100 progress")


def can_claim(
    *,
    status: TaskStatus,
    attempt_count: int,
    max_attempts: int,
    locked_until: datetime | None,
    now: datetime,
) -> bool:
    return (
        status in {TaskStatus.PENDING, TaskStatus.RUNNING}
        and attempt_count < max_attempts
        and (locked_until is None or locked_until <= now)
    )


def can_retry(status: TaskStatus, attempt_count: int, max_attempts: int) -> bool:
    return status is TaskStatus.FAILED and attempt_count < max_attempts
