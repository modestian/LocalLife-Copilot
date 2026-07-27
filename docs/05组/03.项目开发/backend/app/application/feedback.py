"""Feedback application service and repository contract.

Implements the business logic for feedback submission, idempotent
version updates, audit trail and quality filtering defined in:
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.1
- docs/project/大众点评AI智能助手-04-数据库约束说明.md §4.4
- docs/project/大众点评AI智能助手-05-具体设计.md §9.2

Responsibilities (ST-501 acceptance criteria):
- ① Validate that each feedback links to a valid conversation, message
  and original model version.
- ② Enforce idempotency: one user × one message = one active feedback;
  repeated submissions increment version and append to feedback_audits.
- ③ Support filtering by rating, time range, task type and review status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.feedback import DatasetFilter, FeedbackCreate

# ---------------------------------------------------------------------------
# Lightweight data records (decouple application layer from ORM)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MessageInfo:
    """Snapshot of a message and its parent conversation for validation.

    Per ST-501 criterion ①, every feedback must reference a valid
    conversation_id and message_id, and the message must carry a
    model_version_id (the "original model version").
    """

    message_id: UUID
    conversation_id: UUID
    owner_user_id: UUID
    model_version_id: UUID | None
    role: str
    status: str


@dataclass(frozen=True, slots=True)
class FeedbackRecord:
    """In-memory representation of a feedback entry.

    Mirrors the columns of the ``feedback`` table without importing the
    SQLAlchemy model, so the application layer stays framework-agnostic.
    """

    id: UUID
    user_id: UUID
    message_id: UUID
    rating: int
    correction: str | None = None
    reason_codes: list[str] = field(default_factory=list)
    pii_flagged: bool = False
    review_status: str = "PENDING_REVIEW"
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class FeedbackAuditRecord:
    """Append-only audit entry for a feedback version change."""

    id: UUID
    feedback_id: UUID
    version_no: int
    rating: int
    changed_by: UUID
    correction_snapshot: str | None = None
    reason_codes_snapshot: list[str] = field(default_factory=list)
    changed_at: datetime | None = None


# ---------------------------------------------------------------------------
# Repository contract (Protocol)
# ---------------------------------------------------------------------------


class FeedbackRepository(Protocol):
    """Port that the infrastructure repository must satisfy.

    Implementations may be async SQLAlchemy (production) or a simple
    in-memory store (tests).  Every method is async for consistency.
    """

    async def find_message_info(self, message_id: UUID) -> MessageInfo | None:
        """Return message + conversation metadata for validation.

        Returns ``None`` if the message does not exist.
        """
        ...

    async def find_feedback(self, user_id: UUID, message_id: UUID) -> FeedbackRecord | None:
        """Return the current effective feedback for a user-message pair.

        The UNIQUE(user_id, message_id) constraint guarantees at most one row.
        Returns ``None`` when no feedback exists yet.
        """
        ...

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
        """Insert a new feedback entry (version=1) and append an audit row."""
        ...

    async def update_feedback(
        self,
        *,
        feedback_id: UUID,
        rating: int,
        correction: str | None,
        reason_codes: list[str],
        changed_by: UUID,
    ) -> FeedbackRecord:
        """Update an existing feedback: increment version and append audit.

        The old rating/correction/reason_codes snapshot is preserved in
        ``feedback_audits`` by the implementation.
        """
        ...

    async def query_feedbacks(self, filter: DatasetFilter) -> list[FeedbackRecord]:
        """Return feedback entries matching the given filter conditions.

        Supports filtering by rating, time range, task type and review status
        per ST-501 acceptance criterion ③.
        """
        ...


# ---------------------------------------------------------------------------
# Domain errors
# ---------------------------------------------------------------------------


class FeedbackError(ValueError):
    """Base error for feedback domain violations."""


class InvalidMessageReferenceError(FeedbackError):
    """The referenced message or conversation does not exist (criterion ①)."""


class ConversationMismatchError(FeedbackError):
    """The message does not belong to the specified conversation (criterion ①)."""


class MissingModelError(FeedbackError):
    """The message has no associated model version (criterion ①)."""


class NegativeFeedbackContentError(FeedbackError):
    """A thumbs-down feedback requires reason_codes or correction (§4.4)."""


# ---------------------------------------------------------------------------
# Application service
# ---------------------------------------------------------------------------


class FeedbackService:
    """Orchestrates feedback submission, idempotent updates and quality filtering.

    Delegates persistence to :class:`FeedbackRepository` and applies business
    rules from the documentation:
    - ① Validates conversation/message/model-version reference chain.
    - ② Enforces one feedback per user-message; repeated calls update version.
    - ③ Exposes filtered querying for dataset generation.
    """

    def __init__(self, repository: FeedbackRepository) -> None:
        self._repository = repository

    async def submit_feedback(
        self,
        user_id: UUID,
        payload: FeedbackCreate,
    ) -> FeedbackRecord:
        """Submit or update feedback with full validation.

        Steps:
        1. Validate message existence and conversation linkage.
        2. Validate model_version_id presence (original model version).
        3. For negative ratings, require at least one reason_code or correction.
        4. Check existing feedback for idempotency:
           - Not found → create (version=1)
           - Found → update (version++ + audit)

        Returns the current effective :class:`FeedbackRecord`.
        """
        # 1. Message + conversation validation (criterion ①)
        message = await self._repository.find_message_info(payload.message_id)
        if message is None:
            raise InvalidMessageReferenceError(f"Message {payload.message_id} not found")
        if message.conversation_id != payload.conversation_id:
            raise ConversationMismatchError(
                f"Message {payload.message_id} belongs to conversation "
                f"{message.conversation_id}, not {payload.conversation_id}"
            )

        # 2. Model version validation (criterion ①: "原始模型版本")
        if message.model_version_id is None:
            raise MissingModelError(f"Message {payload.message_id} has no associated model version")

        # 3. Negative feedback content rule (§4.4)
        if payload.rating == -1:
            has_content = bool(payload.reason_codes) or bool(payload.correction)
            if not has_content:
                raise NegativeFeedbackContentError(
                    "Thumbs-down feedback requires at least one reason_code or a correction text"
                )

        # 4. Idempotent upsert (criterion ②)
        existing = await self._repository.find_feedback(user_id, payload.message_id)
        if existing is None:
            return await self._repository.create_feedback(
                user_id=user_id,
                message_id=payload.message_id,
                rating=payload.rating,
                correction=payload.correction,
                reason_codes=payload.reason_codes,
                changed_by=user_id,
            )
        return await self._repository.update_feedback(
            feedback_id=existing.id,
            rating=payload.rating,
            correction=payload.correction,
            reason_codes=payload.reason_codes,
            changed_by=user_id,
        )

    async def query_feedbacks(self, filter: DatasetFilter) -> list[FeedbackRecord]:
        """Return feedback entries matching the filter (criterion ③)."""
        return await self._repository.query_feedbacks(filter)
