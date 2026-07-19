from datetime import datetime
from uuid import UUID

import pytest

from app.application.conversations import (
    ConversationNotFound,
    ConversationStatus,
    ConversationView,
    MessageRole,
    MessageStatus,
    MessageView,
    SourceView,
)
from app.core.ids import uuid7
from app.infrastructure.cache.conversations import RedisConversationMemory


class MemoryFactRepository:
    def __init__(self, owner_id: UUID, conversation_id: UUID, messages: list[MessageView]) -> None:
        self.owner_id = owner_id
        self.conversation_id = conversation_id
        self.messages = messages
        self.mysql_reads = 0

    async def get_conversation(self, conversation_id: UUID, owner_user_id: UUID):
        if conversation_id != self.conversation_id or owner_user_id != self.owner_id:
            raise ConversationNotFound("conversation not found")
        now = datetime(2026, 7, 19)
        return ConversationView(
            id=conversation_id,
            owner_user_id=owner_user_id,
            title=None,
            status=ConversationStatus.ACTIVE,
            memory_backend="REDIS",
            current_branch_message_id=None,
            settings={},
            version=1,
            created_at=now,
            updated_at=now,
        )

    async def list_recent_messages(
        self, conversation_id: UUID, owner_user_id: UUID, *, limit: int
    ) -> list[MessageView]:
        await self.get_conversation(conversation_id, owner_user_id)
        self.mysql_reads += 1
        return self.messages[-limit:]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str | bytes] = {}
        self.fail = False

    async def get(self, key: str):
        if self.fail:
            raise ConnectionError("redis unavailable")
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int):
        assert ex > 0
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.values[key] = value

    async def delete(self, *keys: str):
        return sum(self.values.pop(key, None) is not None for key in keys)


def message(conversation_id: UUID, sequence_no: int) -> MessageView:
    source = SourceView(
        chunk_id=uuid7(),
        rank_no=1,
        source_location_snapshot="doc.pdf#page=2",
        content_snapshot="环境安静",
        score=0.9,
        raw_score=12.0,
    )
    return MessageView(
        id=uuid7(),
        conversation_id=conversation_id,
        parent_message_id=None,
        sequence_no=sequence_no,
        request_id=f"request-{sequence_no}",
        role=MessageRole.ASSISTANT,
        content="推荐青禾",
        status=MessageStatus.COMPLETED,
        model_version_id=None,
        prompt_tokens=10,
        completion_tokens=5,
        latency_ms=20,
        error_code=None,
        created_at=datetime(2026, 7, 19, 8, sequence_no),
        sources=(source,),
    )


@pytest.mark.asyncio
async def test_cache_miss_recovers_messages_and_sources_from_mysql() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    repository = MemoryFactRepository(owner_id, conversation_id, [message(conversation_id, 1)])
    redis = FakeRedis()
    memory = RedisConversationMemory(repository, redis)  # type: ignore[arg-type]

    restored = await memory.load(conversation_id, owner_id)
    cached = await memory.load(conversation_id, owner_id)

    assert restored == cached
    assert restored[0].sources[0].content_snapshot == "环境安静"
    assert repository.mysql_reads == 1


@pytest.mark.asyncio
async def test_redis_failure_still_returns_mysql_facts() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    repository = MemoryFactRepository(owner_id, conversation_id, [message(conversation_id, 1)])
    redis = FakeRedis()
    redis.fail = True

    restored = await RedisConversationMemory(repository, redis).load(  # type: ignore[arg-type]
        conversation_id, owner_id
    )

    assert [item.sequence_no for item in restored] == [1]
    assert repository.mysql_reads == 1


@pytest.mark.asyncio
async def test_cache_is_never_read_before_owner_validation() -> None:
    owner_id, attacker_id, conversation_id = uuid7(), uuid7(), uuid7()
    repository = MemoryFactRepository(owner_id, conversation_id, [message(conversation_id, 1)])
    redis = FakeRedis()
    memory = RedisConversationMemory(repository, redis)  # type: ignore[arg-type]
    await memory.load(conversation_id, owner_id)

    with pytest.raises(ConversationNotFound):
        await memory.load(conversation_id, attacker_id)


@pytest.mark.asyncio
async def test_corrupt_cache_is_replaced_from_mysql() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    repository = MemoryFactRepository(owner_id, conversation_id, [message(conversation_id, 1)])
    redis = FakeRedis()
    redis.values[f"conversation:memory:v1:{conversation_id}"] = "not-json"

    restored = await RedisConversationMemory(repository, redis).load(  # type: ignore[arg-type]
        conversation_id, owner_id
    )

    assert len(restored) == 1
    assert repository.mysql_reads == 1
