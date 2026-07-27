from collections import defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.conversations import (
    ConversationNotFound,
    ConversationStatus,
    ConversationView,
    MessageInput,
    MessageNotFound,
    MessageRole,
    MessageStatus,
    MessageView,
    SourceView,
)
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource

_SCORE_QUANTUM = Decimal("0.0000001")


class SQLAlchemyConversationRepository:
    """MySQL fact repository; every read is scoped to the owning user."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_conversation(
        self,
        owner_user_id: UUID,
        *,
        title: str | None = None,
        settings: dict[str, object] | None = None,
    ) -> ConversationView:
        async with self._session_factory() as session, session.begin():
            row = Conversation(
                owner_user_id=owner_user_id,
                title=title.strip() if title else None,
                settings_json=dict(settings or {}),
            )
            session.add(row)
            await session.flush()
            return _conversation_view(row)

    async def get_conversation(
        self, conversation_id: UUID, owner_user_id: UUID
    ) -> ConversationView:
        async with self._session_factory() as session:
            row = await _owned_conversation(session, conversation_id, owner_user_id)
            return _conversation_view(row)

    async def list_conversations(
        self, owner_user_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[ConversationView]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1 to 100 and offset must not be negative")
        async with self._session_factory() as session:
            message_counts = (
                select(
                    Message.conversation_id.label("conversation_id"),
                    func.count(Message.id).label("message_count"),
                )
                .group_by(Message.conversation_id)
                .subquery()
            )
            rows = (
                await session.execute(
                    select(
                        Conversation,
                        func.coalesce(message_counts.c.message_count, 0),
                    )
                    .outerjoin(
                        message_counts,
                        message_counts.c.conversation_id == Conversation.id,
                    )
                    .where(
                        Conversation.owner_user_id == owner_user_id,
                        Conversation.deleted_at.is_(None),
                        Conversation.status != ConversationStatus.DELETED.value,
                    )
                    .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [
                _conversation_view(row, message_count=int(message_count))
                for row, message_count in rows
            ]

    async def append_message(
        self, conversation_id: UUID, owner_user_id: UUID, payload: MessageInput
    ) -> MessageView:
        async with self._session_factory() as session, session.begin():
            conversation = await _owned_conversation(
                session, conversation_id, owner_user_id, lock=True
            )

            if payload.request_id is not None:
                existing = await session.scalar(
                    select(Message).where(
                        Message.conversation_id == conversation_id,
                        Message.request_id == payload.request_id,
                    )
                )
                if existing is not None:
                    sources = await _sources_for_messages(session, [existing.id])
                    return _message_view(existing, sources.get(existing.id, ()))

            parent_message_id = payload.parent_message_id or conversation.current_branch_message_id
            if parent_message_id is not None:
                parent_exists = await session.scalar(
                    select(Message.id).where(
                        Message.id == parent_message_id,
                        Message.conversation_id == conversation_id,
                    )
                )
                if parent_exists is None:
                    raise MessageNotFound("parent message not found in conversation")

            last_sequence = await session.scalar(
                select(func.max(Message.sequence_no)).where(
                    Message.conversation_id == conversation_id
                )
            )
            row = Message(
                conversation_id=conversation_id,
                parent_message_id=parent_message_id,
                sequence_no=(last_sequence or 0) + 1,
                request_id=payload.request_id,
                role=payload.role.value,
                content=payload.content,
                status=payload.status.value,
                model_version_id=payload.model_version_id,
                prompt_tokens=payload.prompt_tokens,
                completion_tokens=payload.completion_tokens,
                latency_ms=payload.latency_ms,
                error_code=payload.error_code,
            )
            session.add(row)
            await session.flush()

            source_rows = []
            for source in payload.sources:
                source_row = MessageSource(
                    message_id=row.id,
                    chunk_id=source.chunk_id,
                    rank_no=source.rank_no,
                    score=_stored_score(source.score),
                    raw_score=source.raw_score,
                    source_location_snapshot=source.source_location_snapshot,
                    content_snapshot=source.content_snapshot,
                )
                session.add(source_row)
                source_rows.append(source_row)

            conversation.current_branch_message_id = row.id
            conversation.updated_at = utc_now()
            await session.flush()
            return _message_view(row, tuple(source_rows))

    async def list_messages(
        self,
        conversation_id: UUID,
        owner_user_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> list[MessageView]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if after_sequence is not None and after_sequence < 0:
            raise ValueError("after_sequence must not be negative")
        async with self._session_factory() as session:
            conversation = await _owned_conversation(session, conversation_id, owner_user_id)
            all_rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.sequence_no)
                )
            ).all()
            rows = _visible_branch_rows(all_rows, conversation.current_branch_message_id)
            if after_sequence is not None:
                rows = [row for row in rows if row.sequence_no > after_sequence]
            rows = rows[:limit]
            sources = await _sources_for_messages(session, [row.id for row in rows])
            return [_message_view(row, sources.get(row.id, ())) for row in rows]

    async def list_recent_messages(
        self, conversation_id: UUID, owner_user_id: UUID, *, limit: int = 20
    ) -> list[MessageView]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        async with self._session_factory() as session:
            conversation = await _owned_conversation(session, conversation_id, owner_user_id)
            all_rows = (
                await session.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation_id)
                    .order_by(Message.sequence_no)
                )
            ).all()
            rows = _visible_branch_rows(all_rows, conversation.current_branch_message_id)[-limit:]
            sources = await _sources_for_messages(session, [row.id for row in rows])
            return [_message_view(row, sources.get(row.id, ())) for row in rows]

    async def delete_conversation(self, conversation_id: UUID, owner_user_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            row = await _owned_conversation(session, conversation_id, owner_user_id, lock=True)
            row.status = ConversationStatus.DELETED.value
            row.deleted_at = utc_now()

    async def update_settings(
        self, conversation_id: UUID, owner_user_id: UUID, settings: dict[str, object]
    ) -> ConversationView:
        async with self._session_factory() as session, session.begin():
            row = await _owned_conversation(session, conversation_id, owner_user_id, lock=True)
            row.settings_json = {**dict(row.settings_json), **settings}
            row.updated_at = utc_now()
            await session.flush()
            return _conversation_view(row)

    async def truncate(
        self, conversation_id: UUID, owner_user_id: UUID, message_id: UUID
    ) -> ConversationView:
        async with self._session_factory() as session, session.begin():
            conversation = await _owned_conversation(
                session, conversation_id, owner_user_id, lock=True
            )
            target = await session.scalar(
                select(Message).where(
                    Message.id == message_id,
                    Message.conversation_id == conversation_id,
                )
            )
            if target is None:
                raise MessageNotFound("truncate target not found in conversation")
            # Truncation is a logical branch move. Historical messages and their
            # sources remain durable for audit/recovery and can form another branch.
            conversation.current_branch_message_id = target.id
            conversation.settings_json = _settings_after_truncate(dict(conversation.settings_json))
            conversation.updated_at = utc_now()
            await session.flush()
            return _conversation_view(conversation)


def _settings_after_truncate(settings: dict[str, object]) -> dict[str, object]:
    """Drop derived memory so abandoned-branch facts cannot leak into later turns."""
    settings.pop("_memory_summary", None)
    settings.pop("constraints", None)
    return settings


def _stored_score(score: float | None) -> Decimal | None:
    """Match the message_sources.score NUMERIC(8, 7) scale before MySQL insertion."""
    return Decimal(str(score)).quantize(_SCORE_QUANTUM) if score is not None else None


def _visible_branch_rows(
    rows: list[Message], current_branch_message_id: UUID | None
) -> list[Message]:
    """Return only ancestors of the current branch head, in conversation order.

    Early installations created messages without parent pointers. When the current
    head is such a legacy message, sequence order is used as a compatibility path.
    """
    if current_branch_message_id is None:
        return []
    by_id = {row.id: row for row in rows}
    head = by_id.get(current_branch_message_id)
    if head is None:
        return []
    if head.parent_message_id is None:
        return [row for row in rows if row.sequence_no <= head.sequence_no]

    visible: list[Message] = []
    seen: set[UUID] = set()
    cursor: Message | None = head
    while cursor is not None and cursor.id not in seen:
        visible.append(cursor)
        seen.add(cursor.id)
        cursor = by_id.get(cursor.parent_message_id) if cursor.parent_message_id else None
    visible.reverse()
    return visible


async def _owned_conversation(
    session: AsyncSession,
    conversation_id: UUID,
    owner_user_id: UUID,
    *,
    lock: bool = False,
) -> Conversation:
    statement = select(Conversation).where(
        Conversation.id == conversation_id,
        Conversation.owner_user_id == owner_user_id,
        Conversation.deleted_at.is_(None),
        Conversation.status != ConversationStatus.DELETED.value,
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        # Deliberately do not reveal whether an inaccessible conversation exists.
        raise ConversationNotFound("conversation not found")
    return row


async def _sources_for_messages(
    session: AsyncSession, message_ids: list[UUID]
) -> dict[UUID, tuple[MessageSource, ...]]:
    if not message_ids:
        return {}
    rows = (
        await session.scalars(
            select(MessageSource)
            .where(MessageSource.message_id.in_(message_ids))
            .order_by(MessageSource.message_id, MessageSource.rank_no)
        )
    ).all()
    grouped: dict[UUID, list[MessageSource]] = defaultdict(list)
    for row in rows:
        grouped[row.message_id].append(row)
    return {message_id: tuple(values) for message_id, values in grouped.items()}


def _conversation_view(row: Conversation, *, message_count: int = 0) -> ConversationView:
    return ConversationView(
        id=row.id,
        owner_user_id=row.owner_user_id,
        title=row.title,
        status=ConversationStatus(row.status),
        memory_backend=row.memory_backend,
        current_branch_message_id=row.current_branch_message_id,
        settings=dict(row.settings_json),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        message_count=message_count,
    )


def _message_view(row: Message, source_rows: tuple[MessageSource, ...]) -> MessageView:
    return MessageView(
        id=row.id,
        conversation_id=row.conversation_id,
        parent_message_id=row.parent_message_id,
        sequence_no=row.sequence_no,
        request_id=row.request_id,
        role=MessageRole(row.role),
        content=row.content,
        status=MessageStatus(row.status),
        model_version_id=row.model_version_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        latency_ms=row.latency_ms,
        error_code=row.error_code,
        created_at=row.created_at,
        sources=tuple(
            SourceView(
                chunk_id=source.chunk_id,
                rank_no=source.rank_no,
                source_location_snapshot=source.source_location_snapshot,
                content_snapshot=source.content_snapshot,
                score=float(source.score) if source.score is not None else None,
                raw_score=source.raw_score,
            )
            for source in source_rows
        ),
    )
