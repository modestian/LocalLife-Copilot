"""Durable conversation recovery and bounded context-window summarization."""

from __future__ import annotations

import re
from collections.abc import Awaitable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Protocol
from uuid import UUID

from app.agents.state import ChatState
from app.application.conversations import (
    ConversationRepository,
    ConversationView,
    MessageRole,
    MessageView,
)

SUMMARY_SETTINGS_KEY = "_memory_summary"


class ConversationHistoryAdapter(Protocol):
    """Optional hot-history adapter; durable facts remain in the repository."""

    async def load(self, conversation_id: UUID, owner_user_id: UUID) -> list[MessageView]: ...

    async def invalidate(self, conversation_id: UUID) -> None: ...


class ConversationSummarizer(Protocol):
    def summarize(
        self,
        messages: tuple[MessageView, ...],
        *,
        previous_summary: str | None = None,
    ) -> str | Awaitable[str]: ...


@dataclass(frozen=True, slots=True)
class MemoryWindow:
    """Model-ready memory containing a bounded raw tail and a durable summary."""

    conversation: ConversationView
    messages: tuple[MessageView, ...]
    history_summary: str
    summarized_through_message_id: UUID | None
    estimated_tokens: int

    def state_update(self) -> dict[str, object]:
        return {"history_summary": self.history_summary} if self.history_summary else {}


class ControlledConversationSummarizer:
    """Deterministic fallback that keeps user facts and unresolved assistant questions.

    Production deployments can inject a model-backed implementation through the
    ``ConversationSummarizer`` port. This fallback deliberately excludes sources,
    tool payloads and internal prompts from the persisted summary.
    """

    def __init__(self, *, max_chars: int = 2000) -> None:
        if max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        self._max_chars = max_chars

    def summarize(
        self,
        messages: tuple[MessageView, ...],
        *,
        previous_summary: str | None = None,
    ) -> str:
        facts: list[str] = []
        if previous_summary:
            facts.append(previous_summary.strip())
        for message in messages:
            content = _normalize_content(message.content)
            if not content:
                continue
            if message.role is MessageRole.USER:
                facts.append(f"用户：{content}")
            elif message.role is MessageRole.ASSISTANT and _looks_unresolved(content):
                facts.append(f"待确认：{content}")
        summary = "\n".join(dict.fromkeys(facts))
        if len(summary) <= self._max_chars:
            return summary
        return summary[: self._max_chars - 1].rstrip() + "…"


class ConversationMemoryService:
    """Restore an owned branch and compact old turns into durable summary metadata."""

    def __init__(
        self,
        repository: ConversationRepository,
        history_adapter: ConversationHistoryAdapter | None = None,
        summarizer: ConversationSummarizer | None = None,
        *,
        context_turns: int = 10,
        token_limit: int = 2048,
        chars_per_token: int = 2,
        page_size: int = 100,
    ) -> None:
        if not 1 <= context_turns <= 50:
            raise ValueError("context_turns must be between 1 and 50")
        if token_limit <= 0 or chars_per_token <= 0:
            raise ValueError("token_limit and chars_per_token must be positive")
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        self._repository = repository
        self._history_adapter = history_adapter
        self._summarizer = summarizer or ControlledConversationSummarizer()
        self._context_turns = context_turns
        self._token_limit = token_limit
        self._chars_per_token = chars_per_token
        self._page_size = page_size

    async def restore(self, conversation_id: UUID, owner_user_id: UUID) -> MemoryWindow:
        conversation = await self._repository.get_conversation(conversation_id, owner_user_id)
        messages = await self._load_visible_messages(conversation, owner_user_id)
        raw_messages, prefix = self._window(messages, conversation)
        summary, through_id = await self._summary(conversation, prefix)
        return MemoryWindow(
            conversation=conversation,
            messages=raw_messages,
            history_summary=summary,
            summarized_through_message_id=through_id,
            estimated_tokens=sum(
                _estimate_tokens(item.content, self._chars_per_token) for item in raw_messages
            ),
        )

    async def load_state(self, state: ChatState, owner_user_id: UUID) -> dict[str, object]:
        """LangGraph load_memory node helper with ownership validation."""
        window = await self.restore(UUID(state["conversation_id"]), owner_user_id)
        return window.state_update()

    async def truncate(
        self, conversation_id: UUID, owner_user_id: UUID, message_id: UUID
    ) -> ConversationView:
        conversation = await self._repository.truncate(conversation_id, owner_user_id, message_id)
        if self._history_adapter is not None:
            await self._history_adapter.invalidate(conversation_id)
        return conversation

    async def _load_visible_messages(
        self, conversation: ConversationView, owner_user_id: UUID
    ) -> tuple[MessageView, ...]:
        # The hot adapter is enough for short Redis-backed conversations. A full
        # durable scan is used at the cache boundary so no older turn is omitted
        # from the first summary after Redis loss or process restart.
        if self._history_adapter is not None and conversation.memory_backend == "REDIS":
            hot = await self._history_adapter.load(conversation.id, owner_user_id)
            if len(hot) < self._context_turns * 2:
                return tuple(hot)

        rows: list[MessageView] = []
        after_sequence: int | None = None
        while True:
            page = await self._repository.list_messages(
                conversation.id,
                owner_user_id,
                after_sequence=after_sequence,
                limit=self._page_size,
            )
            rows.extend(page)
            if len(page) < self._page_size:
                break
            after_sequence = page[-1].sequence_no
        return tuple(rows)

    def _window(
        self, messages: tuple[MessageView, ...], conversation: ConversationView
    ) -> tuple[tuple[MessageView, ...], tuple[MessageView, ...]]:
        configured_turns = conversation.settings.get("context_turns", self._context_turns)
        turns = configured_turns if isinstance(configured_turns, int) else self._context_turns
        max_messages = max(2, min(50, turns) * 2)
        start = max(0, len(messages) - max_messages)
        token_total = 0
        for index in range(len(messages) - 1, start - 1, -1):
            token_total += _estimate_tokens(messages[index].content, self._chars_per_token)
            if token_total > self._token_limit and index < len(messages) - 1:
                start = index + 1
                break
            start = index
        return messages[start:], messages[:start]

    async def _summary(
        self, conversation: ConversationView, prefix: tuple[MessageView, ...]
    ) -> tuple[str, UUID | None]:
        if not prefix:
            return "", None
        through = prefix[-1]
        stored = _stored_summary(conversation)
        if stored is not None and stored[0] == through.id:
            return stored[1], through.id

        previous_summary: str | None = None
        delta = prefix
        if stored is not None:
            stored_id, stored_text = stored
            position = next((i for i, item in enumerate(prefix) if item.id == stored_id), None)
            if position is not None:
                previous_summary = stored_text
                delta = prefix[position + 1 :]
        result = self._summarizer.summarize(delta, previous_summary=previous_summary)
        summary = await result if isawaitable(result) else result
        summary = _normalize_content(summary)
        await self._repository.update_settings(
            conversation.id,
            conversation.owner_user_id,
            {
                SUMMARY_SETTINGS_KEY: {
                    "text": summary,
                    "through_message_id": str(through.id),
                    "through_sequence_no": through.sequence_no,
                }
            },
        )
        return summary, through.id


def _stored_summary(conversation: ConversationView) -> tuple[UUID, str] | None:
    value = conversation.settings.get(SUMMARY_SETTINGS_KEY)
    if not isinstance(value, dict):
        return None
    try:
        message_id = UUID(str(value["through_message_id"]))
        raw_text = value["text"]
        if not isinstance(raw_text, str):
            return None
        text = _normalize_content(raw_text)
    except (KeyError, TypeError, ValueError):
        return None
    return message_id, text


def _estimate_tokens(content: str, chars_per_token: int) -> int:
    return max(1, (len(content) + chars_per_token - 1) // chars_per_token)


def _normalize_content(content: str) -> str:
    return re.sub(r"\s+", " ", content).strip()


def _looks_unresolved(content: str) -> bool:
    return content.endswith(("?", "？")) or any(
        marker in content for marker in ("请问", "请选择", "还需要", "能否")
    )
