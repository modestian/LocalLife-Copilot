"""Read-only audit query contracts and cursor pagination for TK-103-03."""

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: UUID
    actor_id: UUID
    action: str
    resource_type: str
    resource_id: UUID | None
    request_id: str
    ip_address: bytes | None
    result: str
    before_summary: dict[str, object] | None
    after_summary: dict[str, object] | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuditFilter:
    actor_id: UUID | None = None
    module: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    result: str | None = None


@dataclass(frozen=True, slots=True)
class AuditPage:
    items: tuple[AuditRecord, ...]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ChatLogRecord:
    message_id: UUID
    conversation_id: UUID
    user_id: UUID
    request_id: str | None
    role: str
    status: str
    model_version_id: UUID | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    error_code: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatLogFilter:
    user_id: UUID | None = None
    conversation_id: UUID | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    status: str | None = None


class AuditRepository(Protocol):
    async def query(
        self,
        filters: AuditFilter,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[AuditRecord]: ...


class ChatLogRepository(Protocol):
    async def query_chat_logs(
        self, filters: ChatLogFilter, *, limit: int, offset: int
    ) -> list[ChatLogRecord]: ...


class AuditQueryService:
    def __init__(self, repository: AuditRepository) -> None:
        self._repository = repository

    async def query(
        self,
        filters: AuditFilter,
        *,
        page_size: int = 20,
        cursor: str | None = None,
    ) -> AuditPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        start_time = _naive_utc(filters.start_time)
        end_time = _naive_utc(filters.end_time)
        if start_time and end_time and start_time > end_time:
            raise ValueError("start_time must not be after end_time")
        normalized_result = filters.result.upper() if filters.result else None
        if normalized_result not in {None, "SUCCEEDED", "FAILED", "BLOCKED"}:
            raise ValueError("result must be SUCCEEDED, FAILED or BLOCKED")
        normalized_module = filters.module.strip().upper() if filters.module else None
        normalized = AuditFilter(
            actor_id=filters.actor_id,
            module=normalized_module,
            start_time=start_time,
            end_time=end_time,
            result=normalized_result,
        )
        rows = await self._repository.query(
            normalized,
            limit=page_size + 1,
            cursor=decode_cursor(cursor) if cursor else None,
        )
        page_rows = rows[:page_size]
        next_cursor = None
        if len(rows) > page_size and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(last.created_at, last.id)
        return AuditPage(tuple(page_rows), next_cursor)


class ChatLogQueryService:
    def __init__(self, repository: ChatLogRepository) -> None:
        self._repository = repository

    async def query(
        self, filters: ChatLogFilter, *, page: int = 1, page_size: int = 20
    ) -> tuple[ChatLogRecord, ...]:
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("page must be positive and page_size must be between 1 and 100")
        start_time = _naive_utc(filters.start_time)
        end_time = _naive_utc(filters.end_time)
        if start_time and end_time and start_time > end_time:
            raise ValueError("start_time must not be after end_time")
        status = filters.status.upper() if filters.status else None
        if status not in {None, "STREAMING", "COMPLETED", "FAILED", "CANCELLED"}:
            raise ValueError("invalid message status")
        rows = await self._repository.query_chat_logs(
            ChatLogFilter(
                user_id=filters.user_id,
                conversation_id=filters.conversation_id,
                start_time=start_time,
                end_time=end_time,
                status=status,
            ),
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return tuple(rows)


def encode_cursor(created_at: datetime, audit_id: UUID) -> str:
    payload = json.dumps(
        {"created_at": _naive_utc(created_at).isoformat(), "id": str(audit_id)},
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(value + padding))
        return datetime.fromisoformat(payload["created_at"]), UUID(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError, binascii.Error) as exc:
        raise ValueError("invalid audit cursor") from exc


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
