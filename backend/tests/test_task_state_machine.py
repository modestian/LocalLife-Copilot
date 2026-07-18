from datetime import timedelta

import pytest

from app.application.tasks import (
    InvalidTaskTransition,
    TaskStage,
    TaskStatus,
    can_claim,
    can_retry,
    cancellation_target,
    validate_progress,
)
from app.infrastructure.db.base import utc_now


def test_pending_and_interruptible_running_tasks_can_be_cancelled() -> None:
    assert cancellation_target(TaskStatus.PENDING, TaskStage.QUEUED) is TaskStatus.CANCELLED
    assert (
        cancellation_target(TaskStatus.RUNNING, TaskStage.CLEANING)
        is TaskStatus.CANCEL_REQUESTED
    )


@pytest.mark.parametrize(
    "stage",
    [TaskStage.PERSISTING, TaskStage.INDEXING, TaskStage.VERIFYING, TaskStage.DELETING],
)
def test_non_interruptible_stages_reject_cancellation(stage: TaskStage) -> None:
    assert cancellation_target(TaskStatus.RUNNING, stage) is None


def test_claim_requires_pending_status_attempt_budget_and_expired_lease() -> None:
    now = utc_now()
    assert can_claim(
        status=TaskStatus.PENDING,
        attempt_count=0,
        max_attempts=3,
        locked_until=now - timedelta(seconds=1),
        now=now,
    )
    assert not can_claim(
        status=TaskStatus.PENDING,
        attempt_count=3,
        max_attempts=3,
        locked_until=None,
        now=now,
    )
    assert can_claim(
        status=TaskStatus.RUNNING,
        attempt_count=1,
        max_attempts=3,
        locked_until=now - timedelta(seconds=1),
        now=now,
    )


def test_only_failed_tasks_with_attempt_budget_can_retry() -> None:
    assert can_retry(TaskStatus.FAILED, 1, 3)
    assert not can_retry(TaskStatus.FAILED, 3, 3)
    assert not can_retry(TaskStatus.SUCCEEDED, 1, 3)


def test_progress_and_success_invariants_are_enforced() -> None:
    validate_progress(TaskStatus.RUNNING, 50)
    with pytest.raises(ValueError, match="between 0 and 100"):
        validate_progress(TaskStatus.RUNNING, 101)
    with pytest.raises(InvalidTaskTransition, match="100 progress"):
        validate_progress(TaskStatus.SUCCEEDED, 99)
