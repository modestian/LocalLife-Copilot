"""Stable, serializable state exchanged by the LangGraph chat nodes."""

from enum import StrEnum
from typing import NotRequired, TypedDict

from app.agents.types import (
    ChatConstraints,
    ChatError,
    ChatIntent,
    RetrievedChunk,
    SafetyResult,
    SourceCitation,
)


class ChatState(TypedDict):
    """The public graph state; never add prompts or model reasoning to this object."""

    conversation_id: str
    user_query: str
    history_summary: NotRequired[str]
    intent: NotRequired[ChatIntent]
    constraints: NotRequired[ChatConstraints]
    retrieved_chunks: NotRequired[tuple[RetrievedChunk, ...]]
    answer: NotRequired[str]
    sources: NotRequired[tuple[SourceCitation, ...]]
    safety_result: NotRequired[SafetyResult]
    error: NotRequired[ChatError]


class StateField(StrEnum):
    CONVERSATION_ID = "conversation_id"
    USER_QUERY = "user_query"
    HISTORY_SUMMARY = "history_summary"
    INTENT = "intent"
    CONSTRAINTS = "constraints"
    RETRIEVED_CHUNKS = "retrieved_chunks"
    ANSWER = "answer"
    SOURCES = "sources"
    SAFETY_RESULT = "safety_result"
    ERROR = "error"


STATE_FIELDS = frozenset(field.value for field in StateField)
FORBIDDEN_REASONING_FIELDS = frozenset(
    {"chain_of_thought", "reasoning", "reasoning_content", "scratchpad", "thoughts"}
)


def validate_state_update(update: object) -> None:
    """Fail fast when a node leaks data or writes outside the state contract."""
    if not isinstance(update, dict):
        raise TypeError("a graph node must return a state update dict")
    keys = set(update)
    forbidden = keys & FORBIDDEN_REASONING_FIELDS
    if forbidden:
        raise ValueError(f"model reasoning must not be stored in graph state: {sorted(forbidden)}")
    unknown = keys - STATE_FIELDS
    if unknown:
        raise ValueError(f"unknown graph state fields: {sorted(unknown)}")
