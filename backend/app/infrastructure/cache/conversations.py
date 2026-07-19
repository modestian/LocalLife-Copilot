import json
from collections.abc import Awaitable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.application.conversations import (
    ConversationRepository,
    MessageRole,
    MessageStatus,
    MessageView,
    SourceView,
)


class AsyncKeyValueStore(Protocol):
    def get(self, key: str) -> Awaitable[str | bytes | None]: ...

    def set(self, key: str, value: str, *, ex: int) -> Awaitable[object]: ...

    def delete(self, *keys: str) -> Awaitable[int]: ...


class RedisConversationMemory:
    """Recent-message cache with owner validation and MySQL read-through recovery."""

    def __init__(
        self,
        repository: ConversationRepository,
        redis: AsyncKeyValueStore,
        *,
        window_size: int = 20,
        ttl_seconds: int = 3600,
        key_prefix: str = "conversation:memory:v1",
    ) -> None:
        if not 1 <= window_size <= 100:
            raise ValueError("window_size must be between 1 and 100")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._repository = repository
        self._redis = redis
        self._window_size = window_size
        self._ttl_seconds = ttl_seconds
        self._key_prefix = key_prefix.rstrip(":")

    async def load(self, conversation_id: UUID, owner_user_id: UUID) -> list[MessageView]:
        # The cache is consulted only after the fact repository proves ownership.
        await self._repository.get_conversation(conversation_id, owner_user_id)
        key = self._key(conversation_id)
        try:
            cached = await self._redis.get(key)
            messages = _decode_cache(cached, conversation_id, owner_user_id)
            if messages is not None:
                return messages
        except Exception:  # Redis failure must not make durable history unavailable.
            pass

        loader = getattr(self._repository, "list_recent_messages", None)
        if loader is not None:
            messages = await loader(conversation_id, owner_user_id, limit=self._window_size)
        else:
            messages = await self._repository.list_messages(
                conversation_id, owner_user_id, limit=self._window_size
            )
        try:
            await self._redis.set(
                key,
                _encode_cache(owner_user_id, messages),
                ex=self._ttl_seconds,
            )
        except Exception:
            pass
        return messages

    async def invalidate(self, conversation_id: UUID) -> None:
        try:
            await self._redis.delete(self._key(conversation_id))
        except Exception:
            pass

    def _key(self, conversation_id: UUID) -> str:
        return f"{self._key_prefix}:{conversation_id}"


def _encode_cache(owner_user_id: UUID, messages: list[MessageView]) -> str:
    return json.dumps(
        {
            "owner_user_id": str(owner_user_id),
            "messages": [_message_to_dict(message) for message in messages],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _decode_cache(
    raw: str | bytes | None, conversation_id: UUID, owner_user_id: UUID
) -> list[MessageView] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
        if value.get("owner_user_id") != str(owner_user_id):
            return None
        messages = [_message_from_dict(item) for item in value["messages"]]
        if any(message.conversation_id != conversation_id for message in messages):
            return None
        pairs = zip(messages, messages[1:], strict=False)
        if any(left.sequence_no >= right.sequence_no for left, right in pairs):
            return None
        return messages
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _message_to_dict(message: MessageView) -> dict[str, object]:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "parent_message_id": str(message.parent_message_id) if message.parent_message_id else None,
        "sequence_no": message.sequence_no,
        "request_id": message.request_id,
        "role": message.role.value,
        "content": message.content,
        "status": message.status.value,
        "model_version_id": str(message.model_version_id) if message.model_version_id else None,
        "prompt_tokens": message.prompt_tokens,
        "completion_tokens": message.completion_tokens,
        "latency_ms": message.latency_ms,
        "error_code": message.error_code,
        "created_at": message.created_at.isoformat(),
        "sources": [
            {
                "chunk_id": str(source.chunk_id),
                "rank_no": source.rank_no,
                "source_location_snapshot": source.source_location_snapshot,
                "content_snapshot": source.content_snapshot,
                "score": source.score,
                "raw_score": source.raw_score,
            }
            for source in message.sources
        ],
    }


def _message_from_dict(value: dict[str, object]) -> MessageView:
    return MessageView(
        id=UUID(str(value["id"])),
        conversation_id=UUID(str(value["conversation_id"])),
        parent_message_id=(
            UUID(str(value["parent_message_id"])) if value.get("parent_message_id") else None
        ),
        sequence_no=int(str(value["sequence_no"])),
        request_id=str(value["request_id"]) if value.get("request_id") is not None else None,
        role=MessageRole(str(value["role"])),
        content=str(value["content"]),
        status=MessageStatus(str(value["status"])),
        model_version_id=(
            UUID(str(value["model_version_id"])) if value.get("model_version_id") else None
        ),
        prompt_tokens=_optional_int(value.get("prompt_tokens")),
        completion_tokens=_optional_int(value.get("completion_tokens")),
        latency_ms=_optional_int(value.get("latency_ms")),
        error_code=str(value["error_code"]) if value.get("error_code") is not None else None,
        created_at=datetime.fromisoformat(str(value["created_at"])),
        sources=tuple(
            SourceView(
                chunk_id=UUID(str(source["chunk_id"])),
                rank_no=int(str(source["rank_no"])),
                source_location_snapshot=str(source["source_location_snapshot"]),
                content_snapshot=str(source["content_snapshot"]),
                score=float(str(source["score"])) if source.get("score") is not None else None,
                raw_score=(
                    float(str(source["raw_score"])) if source.get("raw_score") is not None else None
                ),
            )
            for source in value.get("sources", [])  # type: ignore[union-attr]
        ),
    )


def _optional_int(value: object) -> int | None:
    return int(str(value)) if value is not None else None
