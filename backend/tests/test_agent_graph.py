from collections.abc import Callable

from app.agents.graph import ChatGraphNodes, build_chat_graph
from app.agents.types import ChatConstraints, ChatIntent, SafetyDecision, SafetyResult


def _node(
    calls: list[str], name: str, update: dict[str, object] | None = None
) -> Callable[[dict], dict[str, object]]:
    def invoke(_state: dict, _runtime: object) -> dict[str, object]:
        calls.append(name)
        return dict(update or {})

    return invoke


def _nodes(calls: list[str], *, intent: ChatIntent, constraints: ChatConstraints) -> ChatGraphNodes:
    return ChatGraphNodes(
        input_guard=_node(
            calls, "input_guard", {"safety_result": SafetyResult(SafetyDecision.ALLOW)}
        ),
        load_memory=_node(calls, "load_memory", {"history_summary": "喜欢安静的川菜"}),
        route_intent=_node(calls, "route_intent", {"intent": intent}),
        extract_constraints=_node(calls, "extract_constraints", {"constraints": constraints}),
        ask_question=_node(calls, "ask_question", {"answer": "请补充人均预算和人数。"}),
        hybrid_retrieve=_node(calls, "hybrid_retrieve", {"retrieved_chunks": ()}),
        generate_grounded=_node(
            calls, "generate_grounded", {"answer": "暂无证据。", "sources": ()}
        ),
        generate_general=_node(calls, "generate_general", {"answer": "你好！"}),
        tool_guard=_node(calls, "tool_guard", {"answer": "工具调用由受控工具层处理。"}),
        output_guard=_node(calls, "output_guard"),
        persist=_node(calls, "persist"),
    )


async def test_compiled_graph_runs_knowledge_retrieval_path() -> None:
    calls: list[str] = []
    graph = build_chat_graph(
        _nodes(
            calls,
            intent=ChatIntent.KNOWLEDGE_QUERY,
            constraints=ChatConstraints(budget_cent_per_person_lte=10000, party_size=2),
        )
    )

    result = await graph.ainvoke({"conversation_id": "c-1", "user_query": "推荐川菜"})

    assert result["answer"] == "暂无证据。"
    assert calls == [
        "input_guard",
        "load_memory",
        "route_intent",
        "extract_constraints",
        "hybrid_retrieve",
        "generate_grounded",
        "output_guard",
        "persist",
    ]


async def test_compiled_graph_routes_missing_conditions_to_clarification() -> None:
    calls: list[str] = []
    graph = build_chat_graph(
        _nodes(calls, intent=ChatIntent.KNOWLEDGE_QUERY, constraints=ChatConstraints())
    )

    result = await graph.ainvoke({"conversation_id": "c-1", "user_query": "推荐餐厅"})

    assert result["answer"].startswith("请补充")
    assert "hybrid_retrieve" not in calls
    assert calls[-2:] == ["output_guard", "persist"]


async def test_compiled_graph_routes_general_chat_without_retrieval() -> None:
    calls: list[str] = []
    graph = build_chat_graph(
        _nodes(calls, intent=ChatIntent.GENERAL_CHAT, constraints=ChatConstraints())
    )

    result = await graph.ainvoke({"conversation_id": "c-1", "user_query": "你好"})

    assert result["answer"] == "你好！"
    assert "extract_constraints" not in calls
    assert "hybrid_retrieve" not in calls
