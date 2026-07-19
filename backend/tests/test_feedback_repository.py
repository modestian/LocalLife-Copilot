"""In-memory FeedbackRepository for unit tests.

Provides a simple, deterministic implementation of the FeedbackRepository
Protocol that stores feedbacks and audits in plain lists, making it easy
to assert state without a database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app.application.feedback import (
    FeedbackAuditRecord,
    FeedbackRecord,
    MessageInfo,
)
from app.core.ids import uuid7
from app.domain.feedback import DatasetFilter


class InMemoryFeedbackRepository:
    """In-memory implementation of FeedbackRepository for tests.

    Stores state in plain lists.  All methods are async to match the
    Protocol contract.  ``model_version_id`` is taken from the
    pre-seeded MessageInfo, simulating the real DB join.
    """

    def __init__(self) -> None:
        self._messages: dict[UUID, MessageInfo] = {}
        self._feedbacks: list[FeedbackRecord] = []
        self._audits: list[FeedbackAuditRecord] = []

    # -- seed helpers --------------------------------------------------

    def seed_message(
        self,
        *,
        message_id: UUID,
        conversation_id: UUID,
        owner_user_id: UUID,
        model_version_id: UUID | None = None,
        role: str = "ASSISTANT",
        status: str = "COMPLETED",
    ) -> MessageInfo:
        """Register a message in the in-memory store."""
        info = MessageInfo(
            message_id=message_id,
            conversation_id=conversation_id,
            owner_user_id=owner_user_id,
            model_version_id=model_version_id,
            role=role,
            status=status,
        )
        self._messages[message_id] = info
        return info

    @property
    def audits(self) -> list[FeedbackAuditRecord]:
        """Return all audit records (for assertions)."""
        return list(self._audits)

    # -- FeedbackRepository protocol methods ----------------------------

    async def find_message_info(self, message_id: UUID) -> MessageInfo | None:
        return self._messages.get(message_id)

    async def find_feedback(self, user_id: UUID, message_id: UUID) -> FeedbackRecord | None:
        for fb in self._feedbacks:
            if fb.user_id == user_id and fb.message_id == message_id:
                return fb
        return None

    async def create_feedback(
        self,
        *,
        user_id: UUID,
        message_id: UUID,
        rating: int,
        correction: str | None,
        reason_codes: list[str],
        changed_by: UUID,
    ) -> FeedbackRecord:
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        feedback_id = uuid7()

        record = FeedbackRecord(
            id=feedback_id,
            user_id=user_id,
            message_id=message_id,
            rating=rating,
            correction=correction,
            reason_codes=list(reason_codes),
            pii_flagged=False,
            review_status="PENDING_REVIEW",
            version=1,
            created_at=now,
            updated_at=now,
        )
        self._feedbacks.append(record)

        audit = FeedbackAuditRecord(
            id=uuid7(),
            feedback_id=feedback_id,
            version_no=1,
            rating=rating,
            correction_snapshot=correction,
            reason_codes_snapshot=list(reason_codes),
            changed_by=changed_by,
            changed_at=now,
        )
        self._audits.append(audit)
        return record

    async def update_feedback(
        self,
        *,
        feedback_id: UUID,
        rating: int,
        correction: str | None,
        reason_codes: list[str],
        changed_by: UUID,
    ) -> FeedbackRecord:
        idx = next(
            (i for i, fb in enumerate(self._feedbacks) if fb.id == feedback_id),
            None,
        )
        if idx is None:
            raise ValueError(f"Feedback {feedback_id} not found")

        old = self._feedbacks[idx]
        now = datetime.now(tz=UTC).replace(tzinfo=None)
        new_version = old.version + 1

        updated = FeedbackRecord(
            id=old.id,
            user_id=old.user_id,
            message_id=old.message_id,
            rating=rating,
            correction=correction,
            reason_codes=list(reason_codes),
            pii_flagged=old.pii_flagged,
            review_status=old.review_status,
            version=new_version,
            created_at=old.created_at,
            updated_at=now,
        )
        self._feedbacks[idx] = updated

        audit = FeedbackAuditRecord(
            id=uuid7(),
            feedback_id=feedback_id,
            version_no=new_version,
            rating=rating,
            correction_snapshot=correction,
            reason_codes_snapshot=list(reason_codes),
            changed_by=changed_by,
            changed_at=now,
        )
        self._audits.append(audit)
        return updated

    async def query_feedbacks(self, filter: DatasetFilter) -> list[FeedbackRecord]:
        """Filter feedbacks by the criteria in DatasetFilter."""
        results: list[FeedbackRecord] = []
        for fb in self._feedbacks:
            if filter.rating is not None and fb.rating != filter.rating:
                continue
            if filter.review_status is not None and fb.review_status != filter.review_status:
                continue
            if filter.start_date is not None and fb.created_at is not None:
                if fb.created_at < filter.start_date:
                    continue
            if filter.end_date is not None and fb.created_at is not None:
                if fb.created_at > filter.end_date:
                    continue
            # task_type filtering is metadata-level; skip when None
            results.append(fb)
        return results
