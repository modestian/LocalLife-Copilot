from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class ConversationStatus(StrEnum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"


class MessageRole(StrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class MessageStatus(StrEnum):
    STREAMING = "STREAMING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ConversationNotFound(LookupError):
    """The conversation does not exist, is deleted, or belongs to another user."""


class MessageNotFound(LookupError):
    """The message is not visible in the requested conversation."""


@dataclass(frozen=True, slots=True)
class ConversationView:
    id: UUID
    owner_user_id: UUID
    title: str | None
    status: ConversationStatus
    memory_backend: str
    current_branch_message_id: UUID | None
    settings: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


@dataclass(frozen=True, slots=True)
class SourceInput:
    chunk_id: UUID
    rank_no: int
    source_location_snapshot: str
    content_snapshot: str
    score: float | None = None
    raw_score: float | None = None

    def __post_init__(self) -> None:
        if self.rank_no < 1:
            raise ValueError("rank_no must be positive")
        if not self.source_location_snapshot:
            raise ValueError("source_location_snapshot must not be empty")
        if not self.content_snapshot:
            raise ValueError("content_snapshot must not be empty")


@dataclass(frozen=True, slots=True)
class SourceView:
    chunk_id: UUID
    rank_no: int
    source_location_snapshot: str
    content_snapshot: str
    score: float | None
    raw_score: float | None


@dataclass(frozen=True, slots=True)
class MessageInput:
    role: MessageRole
    content: str
    status: MessageStatus = MessageStatus.COMPLETED
    parent_message_id: UUID | None = None
    request_id: str | None = None
    model_version_id: UUID | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_ms: int | None = None
    error_code: str | None = None
    sources: tuple[SourceInput, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.content and self.status is MessageStatus.COMPLETED:
            raise ValueError("completed message content must not be empty")
        if self.request_id is not None and not 1 <= len(self.request_id) <= 64:
            raise ValueError("request_id must contain 1 to 64 characters")
        for value in (self.prompt_tokens, self.completion_tokens, self.latency_ms):
            if value is not None and value < 0:
                raise ValueError("token counts and latency must not be negative")
        ranks = [source.rank_no for source in self.sources]
        if len(ranks) != len(set(ranks)):
            raise ValueError("source rank_no values must be unique")
        if self.sources and self.role is not MessageRole.ASSISTANT:
            raise ValueError("only assistant messages may have sources")


@dataclass(frozen=True, slots=True)
class MessageView:
    id: UUID
    conversation_id: UUID
    parent_message_id: UUID | None
    sequence_no: int
    request_id: str | None
    role: MessageRole
    content: str
    status: MessageStatus
    model_version_id: UUID | None
    prompt_tokens: int | None
    completion_tokens: int | None
    latency_ms: int | None
    error_code: str | None
    created_at: datetime
    sources: tuple[SourceView, ...] = field(default_factory=tuple)


class ConversationRepository(Protocol):
    async def create_conversation(
        self,
        owner_user_id: UUID,
        *,
        title: str | None = None,
        settings: dict[str, object] | None = None,
    ) -> ConversationView: ...

    async def get_conversation(
        self, conversation_id: UUID, owner_user_id: UUID
    ) -> ConversationView: ...

    async def list_conversations(
        self, owner_user_id: UUID, *, limit: int = 20, offset: int = 0
    ) -> list[ConversationView]: ...

    async def append_message(
        self, conversation_id: UUID, owner_user_id: UUID, payload: MessageInput
    ) -> MessageView: ...

    async def list_messages(
        self,
        conversation_id: UUID,
        owner_user_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 50,
    ) -> list[MessageView]: ...

    async def delete_conversation(self, conversation_id: UUID, owner_user_id: UUID) -> None: ...

    async def update_settings(
        self, conversation_id: UUID, owner_user_id: UUID, settings: dict[str, object]
    ) -> ConversationView: ...

    async def truncate(
        self, conversation_id: UUID, owner_user_id: UUID, message_id: UUID
    ) -> ConversationView: ...
