from datetime import datetime
from typing import Any

import pytest
from sqlalchemy.dialects import mysql

from app.application.conversations import MessageInput, MessageRole, MessageStatus, SourceInput
from app.core.ids import uuid7
from app.infrastructure.db.models.conversations import Conversation, Message
from app.infrastructure.db.repositories.conversations import SQLAlchemyConversationRepository


class ScalarRows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class ExecuteRows(ScalarRows):
    pass


class FakeSession:
    def __init__(self, scalars: list[Any]) -> None:
        self.results = iter(scalars)
        self.statements: list[Any] = []
        self.added: list[Any] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object):
        return None

    def begin(self):
        return self

    async def scalar(self, statement: Any):
        self.statements.append(statement)
        return next(self.results)

    async def scalars(self, statement: Any):
        self.statements.append(statement)
        return ScalarRows(next(self.results))

    async def execute(self, statement: Any):
        self.statements.append(statement)
        return ExecuteRows(next(self.results))

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid7()
            if isinstance(row, Message) and getattr(row, "created_at", None) is None:
                row.created_at = datetime(2026, 7, 19)


class FakeFactory:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    def __call__(self):
        return self.session


def conversation(owner_id):
    now = datetime(2026, 7, 19)
    return Conversation(
        id=uuid7(),
        owner_user_id=owner_id,
        title=None,
        status="ACTIVE",
        memory_backend="REDIS",
        current_branch_message_id=None,
        settings_json={},
        version=1,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


@pytest.mark.asyncio
async def test_append_locks_owned_conversation_and_allocates_next_sequence() -> None:
    owner_id = uuid7()
    row = conversation(owner_id)
    session = FakeSession([row, 4])
    repository = SQLAlchemyConversationRepository(FakeFactory(session))  # type: ignore[arg-type]

    result = await repository.append_message(
        row.id,
        owner_id,
        MessageInput(
            role=MessageRole.USER,
            content="想找安静的咖啡馆",
            status=MessageStatus.COMPLETED,
        ),
    )

    statement = str(session.statements[0].compile(dialect=mysql.dialect()))
    assert "conversations.owner_user_id" in statement
    assert "FOR UPDATE" in statement
    assert result.sequence_no == 5
    assert row.current_branch_message_id == result.id


@pytest.mark.asyncio
async def test_append_quantizes_source_score_to_database_scale() -> None:
    owner_id = uuid7()
    row = conversation(owner_id)
    session = FakeSession([row, 0])
    repository = SQLAlchemyConversationRepository(FakeFactory(session))  # type: ignore[arg-type]

    await repository.append_message(
        row.id,
        owner_id,
        MessageInput(
            role=MessageRole.ASSISTANT,
            content="推荐结果",
            sources=(
                SourceInput(
                    chunk_id=uuid7(),
                    rank_no=1,
                    source_location_snapshot="demo",
                    content_snapshot="证据",
                    score=0.03278688524590164,
                ),
            ),
        ),
    )

    source = next(item for item in session.added if item.__class__.__name__ == "MessageSource")
    assert str(source.score) == "0.0327869"


@pytest.mark.asyncio
async def test_request_id_returns_existing_message_without_allocating_sequence() -> None:
    owner_id = uuid7()
    row = conversation(owner_id)
    existing = Message(
        id=uuid7(),
        conversation_id=row.id,
        parent_message_id=None,
        sequence_no=1,
        request_id="same-request",
        role="USER",
        content="第一条",
        status="COMPLETED",
        model_version_id=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=None,
        error_code=None,
        created_at=datetime(2026, 7, 19),
    )
    session = FakeSession([row, existing, []])
    repository = SQLAlchemyConversationRepository(FakeFactory(session))  # type: ignore[arg-type]

    result = await repository.append_message(
        row.id,
        owner_id,
        MessageInput(role=MessageRole.USER, content="重试", request_id="same-request"),
    )

    assert result.id == existing.id
    assert len(session.statements) == 3
    assert not session.added


@pytest.mark.asyncio
async def test_list_conversations_restores_persisted_message_count() -> None:
    owner_id = uuid7()
    row = conversation(owner_id)
    session = FakeSession([[(row, 4)]])
    repository = SQLAlchemyConversationRepository(FakeFactory(session))  # type: ignore[arg-type]

    result = await repository.list_conversations(owner_id)

    assert result[0].message_count == 4
    statement = str(session.statements[0].compile(dialect=mysql.dialect()))
    assert "count(messages.id)" in statement
    assert "LEFT OUTER JOIN" in statement
