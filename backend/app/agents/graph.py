"""Executable LangGraph topology for the ST-301 conversation workflow."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.routing import route_after_constraints, route_after_intent
from app.agents.state import ChatState, validate_state_update
from app.agents.types import SafetyDecision

type NodeResult = dict[str, object] | Awaitable[dict[str, object]]
type WorkflowNode = Callable[..., NodeResult]


@dataclass(frozen=True, slots=True)
class ChatGraphNodes:
    """All side-effecting behavior injected into the stable graph topology."""

    input_guard: WorkflowNode
    load_memory: WorkflowNode
    route_intent: WorkflowNode
    extract_constraints: WorkflowNode
    ask_question: WorkflowNode
    hybrid_retrieve: WorkflowNode
    generate_grounded: WorkflowNode
    generate_general: WorkflowNode
    tool_guard: WorkflowNode
    output_guard: WorkflowNode
    persist: WorkflowNode


def build_chat_graph(
    nodes: ChatGraphNodes, *, context_schema: type[Any] | None = None
) -> CompiledStateGraph:
    """Compile the documented ST-301 topology into an async executable graph."""

    builder = StateGraph(ChatState, context_schema=context_schema)
    for name in ChatGraphNodes.__dataclass_fields__:
        builder.add_node(name, _validated(getattr(nodes, name)))

    builder.add_edge(START, "input_guard")
    builder.add_conditional_edges(
        "input_guard",
        _route_after_input_guard,
        {"load_memory": "load_memory", "output_guard": "output_guard"},
    )
    builder.add_edge("load_memory", "route_intent")
    builder.add_conditional_edges(
        "route_intent",
        route_after_intent,
        {
            "generate_general": "generate_general",
            "tool_guard": "tool_guard",
            "extract_constraints": "extract_constraints",
        },
    )
    builder.add_conditional_edges(
        "extract_constraints",
        route_after_constraints,
        {"ask_question": "ask_question", "hybrid_retrieve": "hybrid_retrieve"},
    )
    builder.add_edge("hybrid_retrieve", "generate_grounded")
    for terminal_answer_node in (
        "ask_question",
        "generate_grounded",
        "generate_general",
        "tool_guard",
    ):
        builder.add_edge(terminal_answer_node, "output_guard")
    builder.add_conditional_edges(
        "output_guard",
        _route_after_output_guard,
        {"persist": "persist", "end": END},
    )
    builder.add_edge("persist", END)
    return builder.compile()


def _route_after_input_guard(state: ChatState) -> str:
    result = state.get("safety_result")
    if result is not None and result.decision is SafetyDecision.BLOCK:
        return "output_guard"
    return "load_memory"


def _route_after_output_guard(state: ChatState) -> str:
    return "persist" if state.get("answer") else "end"


def _validated(node: WorkflowNode) -> Callable[[ChatState], Awaitable[dict[str, object]]]:
    async def invoke(state: ChatState, runtime: object) -> dict[str, object]:
        result: Any = node(state, runtime)
        if isawaitable(result):
            result = await result
        validate_state_update(result)
        return result

    return invoke