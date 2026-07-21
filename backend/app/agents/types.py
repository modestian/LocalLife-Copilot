"""Framework-neutral value objects used by chat graph nodes and adapters."""

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChatIntent(StrEnum):
    KNOWLEDGE_QUERY = "knowledge_query"
    TOOL_USE = "tool_use"
    GENERAL_CHAT = "general_chat"


class SafetyDecision(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class ChatConstraints:
    distance_meter_lte: int | None = None
    budget_cent_per_person_lte: int | None = None
    cuisines: tuple[str, ...] = ()
    atmospheres: tuple[str, ...] = ()
    scenes: tuple[str, ...] = ()
    party_size: int | None = None
    open_now: bool | None = None

    def __post_init__(self) -> None:
        for name in ("distance_meter_lte", "budget_cent_per_person_lte", "party_size"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    content: str
    score: float
    source_location: str
    merchant_id: str | None = None
    data_updated_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (
            not self.chunk_id.strip()
            or not self.content.strip()
            or not self.source_location.strip()
        ):
            raise ValueError("chunk_id, content and source_location must not be blank")
        if not math.isfinite(self.score):
            raise ValueError("score must be finite")


@dataclass(frozen=True, slots=True)
class SourceCitation:
    chunk_id: str
    rank_no: int
    source_location: str
    content_snapshot: str
    score: float | None = None
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        if self.rank_no <= 0:
            raise ValueError("rank_no must be positive")
        if not self.chunk_id.strip() or not self.source_location.strip():
            raise ValueError("citation identifiers must not be blank")
        if not self.content_snapshot.strip():
            raise ValueError("content_snapshot must not be blank")
        if self.evidence_id is not None and not self.evidence_id.strip():
            raise ValueError("evidence_id must not be blank")


@dataclass(frozen=True, slots=True)
class SafetyResult:
    decision: SafetyDecision
    rule_ids: tuple[str, ...] = ()
    safe_message: str | None = None


@dataclass(frozen=True, slots=True)
class ChatError:
    code: str
    message: str
    retryable: bool = False

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.message.strip():
            raise ValueError("error code and message must not be blank")
