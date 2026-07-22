from dataclasses import replace
from datetime import datetime
from uuid import UUID

import pytest

from app.agents.memory import ConversationMemoryService
from app.application.conversations import (
    ConversationStatus,
    ConversationView,
    MessageRole,
    MessageStatus,
    MessageView,
)
from app.core.ids import uuid7


class FactRepository:
    def __init__(self, conversation: ConversationView, messages: list[MessageView]) -> None:
        self.conversation = conversation
        self.messages = messages
        self.settings_writes: list[dict[str, object]] = []

    async def get_conversation(self, conversation_id: UUID, owner_user_id: UUID):
        assert conversation_id == self.conversation.id
        assert owner_user_id == self.conversation.owner_user_id
        return self.conversation

    async def list_messages(
        self,
        conversation_id: UUID,
        owner_user_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ):
        await self.get_conversation(conversation_id, owner_user_id)
        return [
            item
            for item in self.messages
            if after_sequence is None or item.sequence_no > after_sequence
        ][:limit]

    async def update_settings(
        self, conversation_id: UUID, owner_user_id: UUID, settings: dict[str, object]
    ):
        await self.get_conversation(conversation_id, owner_user_id)
        self.settings_writes.append(settings)
        self.conversation = replace(
            self.conversation,
            settings={**self.conversation.settings, **settings},
        )
        return self.conversation

    async def truncate(self, conversation_id: UUID, owner_user_id: UUID, message_id: UUID):
        await self.get_conversation(conversation_id, owner_user_id)
        self.conversation = replace(
            self.conversation,
            current_branch_message_id=message_id,
            settings={
                key: value
                for key, value in self.conversation.settings.items()
                if key != "_memory_summary"
            },
        )
        return self.conversation


class CountingSummarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, ...], str | None]] = []

    def summarize(self, messages, *, previous_summary=None):
        self.calls.append((tuple(item.sequence_no for item in messages), previous_summary))
        parts = [previous_summary] if previous_summary else []
        parts.extend(item.content for item in messages if item.role is MessageRole.USER)
        return " | ".join(parts)


class HotHistory:
    def __init__(self, messages: list[MessageView]) -> None:
        self.messages = messages
        self.invalidated: list[UUID] = []

    async def load(self, conversation_id: UUID, owner_user_id: UUID):
        return self.messages

    async def invalidate(self, conversation_id: UUID):
        self.invalidated.append(conversation_id)


def conversation(owner_id: UUID, conversation_id: UUID, settings=None) -> ConversationView:
    now = datetime(2026, 7, 21)
    return ConversationView(
        id=conversation_id,
        owner_user_id=owner_id,
        title=None,
        status=ConversationStatus.ACTIVE,
        memory_backend="REDIS",
        current_branch_message_id=None,
        settings=settings or {},
        version=1,
        created_at=now,
        updated_at=now,
    )


def message(conversation_id: UUID, sequence_no: int, role: MessageRole) -> MessageView:
    return MessageView(
        id=uuid7(),
        conversation_id=conversation_id,
        parent_message_id=None,
        sequence_no=sequence_no,
        request_id=None,
        role=role,
        content=f"message-{sequence_no}-" + "内容" * 10,
        status=MessageStatus.COMPLETED,
        model_version_id=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=None,
        error_code=None,
        created_at=datetime(2026, 7, 21, 8, sequence_no),
    )


@pytest.mark.asyncio
async def test_restore_builds_bounded_window_and_persists_summary() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    messages = [
        message(conversation_id, number, MessageRole.USER if number % 2 else MessageRole.ASSISTANT)
        for number in range(1, 7)
    ]
    repository = FactRepository(conversation(owner_id, conversation_id), messages)
    summarizer = CountingSummarizer()
    service = ConversationMemoryService(
        repository,  # type: ignore[arg-type]
        summarizer=summarizer,
        context_turns=1,
        token_limit=100,
    )

    restored = await service.restore(conversation_id, owner_id)
    restored_again = await service.restore(conversation_id, owner_id)

    assert [item.sequence_no for item in restored.messages] == [5, 6]
    assert restored.summarized_through_message_id == messages[3].id
    assert "message-1" in restored.history_summary
    assert repository.settings_writes[0]["_memory_summary"]
    assert restored_again.history_summary == restored.history_summary
    assert len(summarizer.calls) == 1


@pytest.mark.asyncio
async def test_summary_is_incremental_when_window_advances() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    messages = [message(conversation_id, number, MessageRole.USER) for number in range(1, 4)]
    repository = FactRepository(conversation(owner_id, conversation_id), messages)
    summarizer = CountingSummarizer()
    service = ConversationMemoryService(
        repository,  # type: ignore[arg-type]
        summarizer=summarizer,
        context_turns=1,
    )
    first = await service.restore(conversation_id, owner_id)
    repository.messages.append(message(conversation_id, 4, MessageRole.ASSISTANT))

    second = await service.restore(conversation_id, owner_id)

    assert first.summarized_through_message_id == messages[0].id
    assert second.summarized_through_message_id == messages[1].id
    assert summarizer.calls[1][0] == (2,)
    assert summarizer.calls[1][1] == first.history_summary


@pytest.mark.asyncio
async def test_truncate_invalidates_hot_history() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    target = message(conversation_id, 1, MessageRole.USER)
    repository = FactRepository(conversation(owner_id, conversation_id), [target])
    hot = HotHistory([target])
    service = ConversationMemoryService(repository, hot)  # type: ignore[arg-type]

    result = await service.truncate(conversation_id, owner_id, target.id)

    assert result.current_branch_message_id == target.id
    assert hot.invalidated == [conversation_id]


@pytest.mark.asyncio
async def test_invalidate_delegates_to_hot_history() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    repository = FactRepository(conversation(owner_id, conversation_id), [])
    hot = HotHistory([])
    service = ConversationMemoryService(repository, hot)  # type: ignore[arg-type]

    await service.invalidate(conversation_id)

    assert hot.invalidated == [conversation_id]


@pytest.mark.asyncio
async def test_invalidate_without_hot_history_is_a_safe_noop() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    repository = FactRepository(conversation(owner_id, conversation_id), [])
    service = ConversationMemoryService(repository)  # type: ignore[arg-type]

    await service.invalidate(conversation_id)


@pytest.mark.asyncio
async def test_empty_summary_watermark_is_reused() -> None:
    owner_id, conversation_id = uuid7(), uuid7()
    messages = [message(conversation_id, number, MessageRole.ASSISTANT) for number in range(1, 4)]
    repository = FactRepository(conversation(owner_id, conversation_id), messages)
    summarizer = CountingSummarizer()
    service = ConversationMemoryService(
        repository,  # type: ignore[arg-type]
        summarizer=summarizer,
        context_turns=1,
    )

    await service.restore(conversation_id, owner_id)
    await service.restore(conversation_id, owner_id)

    assert len(summarizer.calls) == 1
