"""Node and external service ports for the chat graph."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.agents.state import ChatState, StateField
from app.agents.types import ChatConstraints, RetrievedChunk

type StateUpdate = dict[str, object]
type NodeResult = StateUpdate | Awaitable[StateUpdate]
type GraphNode = Callable[[ChatState], NodeResult]


@dataclass(frozen=True, slots=True)
class NodeContract:
    """Documents the state keys a node consumes and may update."""

    name: str
    requires: frozenset[StateField]
    produces: frozenset[StateField]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("node name must not be blank")
        if self.requires & self.produces:
            raise ValueError("node fields cannot be both required and produced")


@dataclass(frozen=True, slots=True)
class ModelInput:
    task: str
    prompt: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task.strip() or not self.prompt.strip():
            raise ValueError("model task and prompt must not be blank")


@dataclass(frozen=True, slots=True)
class ModelPrediction:
    text: str
    model_version: str
    structured: Mapping[str, Any] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@runtime_checkable
class ModelAdapter(Protocol):
    """Hides provider, base-model and PEFT/LoRA details from graph nodes."""

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]: ...


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    tenant_id: str
    knowledge_base_ids: frozenset[str]
    resource_scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be blank")


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    query: str
    scope: RetrievalScope
    constraints: ChatConstraints = field(default_factory=ChatConstraints)
    top_k: int = 5

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("retrieval query must not be blank")
        if self.top_k <= 0:
            raise ValueError("top_k must be positive")


@runtime_checkable
class RetrieverAdapter(Protocol):
    """Permission-aware retrieval port exposed to graph nodes."""

    def retrieve(self, request: RetrievalRequest) -> Sequence[RetrievedChunk]: ...
