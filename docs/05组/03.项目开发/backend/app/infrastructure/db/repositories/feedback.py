"""SQLAlchemy implementation of FeedbackRepository.

Provides production-grade persistence for feedback entries and their audit
trails, implementing the :class:`~app.application.feedback.FeedbackRepository`
Protocol.

All methods are async and use ``async_sessionmaker`` for connection management,
following the same pattern as :class:`SQLAlchemyAuthRepository`.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.feedback import (
    FeedbackRecord,
    MessageInfo,
)
from app.core.ids import uuid7
from app.domain.feedback import DatasetFilter
from app.infrastructure.db.models.conversations import Conversation, Message
from app.infrastructure.db.models.feedback import Feedback, FeedbackAudit


def _orm_to_record(fb: Feedback) -> FeedbackRecord:
    """Convert a Feedback ORM row to a framework-agnostic FeedbackRecord."""
    return FeedbackRecord(
        id=fb.id,
        user_id=fb.user_id,
        message_id=fb.message_id,
        rating=fb.rating,
        correction=fb.correction,
        reason_codes=fb.reason_codes_json or [],
        pii_flagged=bool(fb.pii_flagged),
        review_status=fb.review_status,
        version=fb.version,
        created_at=fb.created_at,
        updated_at=fb.updated_at,
    )


class SQLAlchemyFeedbackRepository:
    """Production FeedbackRepository backed by async SQLAlchemy.

    Implements all five methods of the FeedbackRepository Protocol:
    ``find_message_info``, ``find_feedback``, ``create_feedback``,
    ``update_feedback`` and ``query_feedbacks``.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------
    # find_message_info — JOIN messages + conversations
    # ------------------------------------------------------------------

    async def find_message_info(self, message_id: UUID) -> MessageInfo | None:
        """Return message + conversation metadata for validation.

        Per ST-501 criterion ①: every feedback must reference a valid
        conversation, message and model version.
        """
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(Message, Conversation)
                    .join(
                        Conversation,
                        Conversation.id == Message.conversation_id,
                    )
                    .where(Message.id == message_id)
                )
            ).one_or_none()
            if row is None:
                return None
            message, conversation = row
            return MessageInfo(
                message_id=message.id,
                conversation_id=message.conversation_id,
                owner_user_id=conversation.owner_user_id,
                model_version_id=message.model_version_id,
                role=message.role,
                status=message.status,
            )

    # ------------------------------------------------------------------
    # find_feedback — SELECT by (user_id, message_id)
    # ------------------------------------------------------------------

    async def find_feedback(self, user_id: UUID, message_id: UUID) -> FeedbackRecord | None:
        """Return the current effective feedback for a user-message pair.

        The UNIQUE(user_id, message_id) constraint guarantees at most one row.
        """
        async with self._session_factory() as session:
            fb = await session.scalar(
                select(Feedback)
                .where(Feedback.user_id == user_id)
                .where(Feedback.message_id == message_id)
            )
            if fb is None:
                return None
            return _orm_to_record(fb)

    # ------------------------------------------------------------------
    # create_feedback — INSERT feedback + INSERT audit
    # ------------------------------------------------------------------

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
        async with self._session_factory() as session, session.begin():
            feedback = Feedback(
                id=uuid7(),
                user_id=user_id,
                message_id=message_id,
                rating=rating,
                correction=correction,
                reason_codes_json=reason_codes,
                pii_flagged=False,
                review_status="PENDING_REVIEW",
            )
            session.add(feedback)

            audit = FeedbackAudit(
                id=uuid7(),
                feedback_id=feedback.id,
                version_no=1,
                rating=rating,
                correction_snapshot=correction,
                reason_codes_snapshot=list(reason_codes),
                changed_by=changed_by,
            )
            session.add(audit)
            await session.flush()
            await session.refresh(feedback)
            return _orm_to_record(feedback)

    # ------------------------------------------------------------------
    # update_feedback — UPDATE feedback + INSERT audit
    # ------------------------------------------------------------------

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

        Uses ``with_for_update()`` to lock the row during the transaction,
        preventing concurrent modifications.  The VersionMixin's
        ``version_id_col`` provides an additional optimistic-locking guard.
        """
        async with self._session_factory() as session, session.begin():
            fb = await session.scalar(
                select(Feedback).where(Feedback.id == feedback_id).with_for_update()
            )
            if fb is None:
                raise ValueError(f"Feedback {feedback_id} not found")

            new_version = fb.version + 1

            # Update the current-effective feedback fields
            fb.rating = rating
            fb.correction = correction
            fb.reason_codes_json = list(reason_codes)

            # Append an immutable audit record with the new version snapshot
            audit = FeedbackAudit(
                id=uuid7(),
                feedback_id=feedback_id,
                version_no=new_version,
                rating=rating,
                correction_snapshot=correction,
                reason_codes_snapshot=list(reason_codes),
                changed_by=changed_by,
            )
            session.add(audit)
            await session.flush()
            await session.refresh(fb)
            return _orm_to_record(fb)

    # ------------------------------------------------------------------
    # query_feedbacks — filtered SELECT
    # ------------------------------------------------------------------

    async def query_feedbacks(self, filter: DatasetFilter) -> list[FeedbackRecord]:
        """Return feedback entries matching the filter conditions.

        Supports filtering by rating, review status and time range per
        ST-501 acceptance criterion ③.
        """
        async with self._session_factory() as session:
            stmt = select(Feedback)
            if filter.rating is not None:
                stmt = stmt.where(Feedback.rating == filter.rating)
            if filter.review_status is not None:
                stmt = stmt.where(Feedback.review_status == filter.review_status)
            if filter.start_date is not None:
                stmt = stmt.where(Feedback.created_at >= filter.start_date)
            if filter.end_date is not None:
                stmt = stmt.where(Feedback.created_at <= filter.end_date)
            stmt = stmt.order_by(Feedback.created_at)
            result = await session.execute(stmt)
            return [_orm_to_record(fb) for fb in result.scalars().all()]
