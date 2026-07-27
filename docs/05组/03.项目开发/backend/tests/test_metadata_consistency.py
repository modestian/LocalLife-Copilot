import asyncio
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.application.conversations import MessageInput, MessageRole, MessageStatus
from app.core.ids import uuid7
from app.infrastructure.db.models.conversations import Conversation, Message
from app.infrastructure.db.repositories.conversations import SQLAlchemyConversationRepository


@pytest.fixture
def conversation_engine():
    """Create only the two tables needed by the consistency tests.

    SQLite keeps these tests fast while still exercising SQLAlchemy's real unit of
    work, unique indexes, and version predicates. Foreign-key enforcement is left
    disabled because identity tables are outside TK-102-05's test boundary.
    """
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        # SQLite does not accept MySQL's CURRENT_TIMESTAMP(6), so the compact DDL
        # below mirrors the mapped columns and the constraints under test.
        connection.exec_driver_sql(
            """
            CREATE TABLE conversations (
                id BLOB PRIMARY KEY,
                owner_user_id BLOB NOT NULL,
                title VARCHAR(255),
                status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE',
                memory_backend VARCHAR(16) NOT NULL DEFAULT 'REDIS',
                current_branch_message_id BLOB,
                settings_json JSON NOT NULL,
                deleted_at DATETIME,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                version INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE messages (
                id BLOB PRIMARY KEY,
                conversation_id BLOB NOT NULL,
                parent_message_id BLOB,
                sequence_no INTEGER NOT NULL,
                request_id VARCHAR(64),
                role VARCHAR(16) NOT NULL,
                content TEXT NOT NULL,
                status VARCHAR(16) NOT NULL,
                model_version_id BLOB,
                prompt_tokens INTEGER,
                completion_tokens INTEGER,
                latency_ms INTEGER,
                error_code VARCHAR(64),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_messages_sequence UNIQUE (conversation_id, sequence_no),
                CONSTRAINT uq_messages_request UNIQUE (conversation_id, request_id)
            )
            """
        )
    try:
        yield engine
    finally:
        engine.dispose()


def _conversation() -> Conversation:
    return Conversation(
        id=uuid7(),
        owner_user_id=uuid7(),
        title="初始会话",
        settings_json={},
    )


def _message(conversation_id, *, sequence_no: int, request_id: str) -> Message:
    return Message(
        id=uuid7(),
        conversation_id=conversation_id,
        sequence_no=sequence_no,
        request_id=request_id,
        role=MessageRole.USER.value,
        content="测试消息",
        status=MessageStatus.COMPLETED.value,
    )


def test_message_sequence_and_request_unique_constraints_reject_duplicates(
    conversation_engine,
) -> None:
    conversation = _conversation()
    with Session(conversation_engine) as session:
        session.add(conversation)
        session.commit()
        session.add(_message(conversation.id, sequence_no=1, request_id="request-1"))
        session.commit()

        session.add(_message(conversation.id, sequence_no=1, request_id="request-2"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        session.add(_message(conversation.id, sequence_no=2, request_id="request-1"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_conversation_optimistic_lock_rejects_a_stale_update(conversation_engine) -> None:
    conversation = _conversation()
    with Session(conversation_engine) as setup_session:
        setup_session.add(conversation)
        setup_session.commit()
        conversation_id = conversation.id

    first_session = Session(conversation_engine)
    stale_session = Session(conversation_engine)
    try:
        first_copy = first_session.get(Conversation, conversation_id)
        stale_copy = stale_session.get(Conversation, conversation_id)
        assert first_copy is not None
        assert stale_copy is not None
        assert first_copy.version == stale_copy.version == 1

        first_copy.title = "先提交的标题"
        first_session.commit()
        assert first_copy.version == 2

        stale_copy.title = "过期副本的标题"
        with pytest.raises(StaleDataError):
            stale_session.commit()
        stale_session.rollback()

        with Session(conversation_engine) as verification_session:
            persisted = verification_session.get(Conversation, conversation_id)
            assert persisted is not None
            assert persisted.title == "先提交的标题"
            assert persisted.version == 2
    finally:
        first_session.close()
        stale_session.close()


class _ConcurrentState:
    def __init__(self, conversation: Conversation) -> None:
        self.conversation = conversation
        self.messages: list[Message] = []
        self.row_lock = asyncio.Lock()


class _Transaction:
    def __init__(self, lock: asyncio.Lock) -> None:
        self._lock = lock

    async def __aenter__(self) -> "_Transaction":
        await self._lock.acquire()
        return self

    async def __aexit__(self, *_: object) -> None:
        self._lock.release()


class _ConcurrentSession:
    def __init__(self, state: _ConcurrentState) -> None:
        self._state = state
        self._pending: list[Message] = []

    async def __aenter__(self) -> "_ConcurrentSession":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Transaction:
        return _Transaction(self._state.row_lock)

    async def scalar(self, statement: Any):
        if statement.column_descriptions[0].get("entity") is Conversation:
            return self._state.conversation
        await asyncio.sleep(0)
        return max((message.sequence_no for message in self._state.messages), default=None)

    def add(self, row: Any) -> None:
        if isinstance(row, Message):
            self._pending.append(row)

    async def flush(self) -> None:
        for row in self._pending:
            if row.id is None:
                row.id = uuid7()
            if row.created_at is None:
                row.created_at = datetime(2026, 7, 19)
            self._state.messages.append(row)
        self._pending.clear()
        await asyncio.sleep(0)


class _ConcurrentFactory:
    def __init__(self, state: _ConcurrentState) -> None:
        self._state = state

    def __call__(self) -> _ConcurrentSession:
        return _ConcurrentSession(self._state)


@pytest.mark.asyncio
async def test_concurrent_message_appends_allocate_distinct_monotonic_sequences() -> None:
    conversation = _conversation()
    conversation.version = 1
    conversation.created_at = datetime(2026, 7, 19)
    conversation.updated_at = datetime(2026, 7, 19)
    state = _ConcurrentState(conversation)
    repository = SQLAlchemyConversationRepository(  # type: ignore[arg-type]
        _ConcurrentFactory(state)
    )

    first, second = await asyncio.gather(
        repository.append_message(
            conversation.id,
            conversation.owner_user_id,
            MessageInput(role=MessageRole.USER, content="第一条"),
        ),
        repository.append_message(
            conversation.id,
            conversation.owner_user_id,
            MessageInput(role=MessageRole.USER, content="第二条"),
        ),
    )

    assert sorted((first.sequence_no, second.sequence_no)) == [1, 2]
    assert sorted(message.sequence_no for message in state.messages) == [1, 2]
    assert len({message.id for message in state.messages}) == 2
