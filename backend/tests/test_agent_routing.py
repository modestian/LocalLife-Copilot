from collections.abc import Sequence

from app.agents import (
    ChatConstraints,
    ChatIntent,
    ClarificationPlanner,
    ConstraintExtractor,
    IntentRouter,
    ModelInput,
    ModelPrediction,
    route_after_constraints,
    route_after_intent,
    validate_state_update,
)


class StructuredModel:
    def __init__(self, output: dict[str, object]):
        self.output = output
        self.tasks: list[str] = []

    def predict(self, batch: Sequence[ModelInput]) -> Sequence[ModelPrediction]:
        self.tasks.extend(item.task for item in batch)
        return [ModelPrediction(text="", structured=self.output, model_version="stub-v1")]


def test_intent_router_covers_knowledge_tool_and_general_chat() -> None:
    router = IntentRouter()

    assert router.classify("帮我推荐一家安静的川菜馆") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("总结一下这家店近期的差评") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("请调用地图工具规划路线") is ChatIntent.TOOL_USE
    assert router.classify("你好，今天过得怎么样？") is ChatIntent.GENERAL_CHAT


def test_constraint_extractor_normalizes_all_supported_constraints() -> None:
    constraints = ConstraintExtractor().extract(
        "找一家 1.5 公里内、人均 120 元以内的安静川菜，适合约会，2 人，现在营业"
    )

    assert constraints == ChatConstraints(
        distance_meter_lte=1500,
        budget_cent_per_person_lte=12000,
        cuisines=("川菜",),
        atmospheres=("安静",),
        scenes=("约会",),
        party_size=2,
        open_now=True,
    )


def test_follow_up_merges_retained_constraints_and_routes_to_retrieval() -> None:
    first = ConstraintExtractor().extract("推荐附近安静的日料")
    follow_up_state = {
        "conversation_id": "conversation-1",
        "user_query": "两个人，人均 100 元以内",
        "history_summary": "用户正在寻找附近安静的日料推荐",
        "constraints": first,
    }
    follow_up_state.update(IntentRouter()(follow_up_state))
    follow_up_state.update(ConstraintExtractor()(follow_up_state))

    assert follow_up_state["intent"] is ChatIntent.KNOWLEDGE_QUERY
    assert follow_up_state["constraints"] == ChatConstraints(
        distance_meter_lte=1000,
        budget_cent_per_person_lte=10000,
        cuisines=("日本料理",),
        atmospheres=("安静",),
        party_size=2,
    )
    assert route_after_constraints(follow_up_state) == "hybrid_retrieve"


def test_constraint_extractor_ignores_constraints_from_assistant_history() -> None:
    constraints = ConstraintExtractor().extract(
        "清河面馆",
        existing=ChatConstraints(cuisines=("咖啡",), atmospheres=("安静",)),
        history_summary=(
            "USER: 你好\n"
            "ASSISTANT: 你好，我是探店助手。\n"
            "USER: 我要找店\n\n"
            "[探店条件] 场景：附近随便吃；距离：3 公里内；预算：人均 80 元以内；"
            "人数：2 人；营业状态：当前营业\n"
            "ASSISTANT: 推荐书香咖啡馆，环境安静。"
        ),
    )

    assert constraints == ChatConstraints(
        distance_meter_lte=3000,
        budget_cent_per_person_lte=8000,
        party_size=2,
        open_now=True,
        cuisines=("面食",),
    )


def test_unrelated_input_does_not_inherit_previous_search_intent() -> None:
    router = IntentRouter()
    history = "USER: 推荐附近的店\nASSISTANT: 推荐清河面馆和书香咖啡馆。"
    existing = ChatConstraints(
        distance_meter_lte=3000,
        budget_cent_per_person_lte=8000,
        party_size=2,
    )

    assert (
        router.classify("乃龙", history_summary=history, existing_constraints=existing)
        is ChatIntent.GENERAL_CHAT
    )
    assert (
        router.classify("再来一家", history_summary=history, existing_constraints=existing)
        is ChatIntent.KNOWLEDGE_QUERY
    )


def test_clarification_asks_for_all_missing_key_fields_once() -> None:
    state = {
        "conversation_id": "conversation-1",
        "user_query": "推荐一家浪漫的西餐厅",
        "intent": ChatIntent.KNOWLEDGE_QUERY,
        "constraints": ChatConstraints(cuisines=("西餐",), atmospheres=("浪漫",)),
    }

    decision = ClarificationPlanner().plan(state)
    update = ClarificationPlanner()(state)

    assert decision.needed is True
    assert decision.missing_fields == ("budget_cent_per_person_lte", "party_size")
    assert "人均预算" in decision.question
    assert "用餐人数" in decision.question
    assert update == {"answer": decision.question}
    validate_state_update(update)


def test_review_summary_does_not_trigger_recommendation_clarification() -> None:
    state = {
        "conversation_id": "conversation-1",
        "user_query": "总结一下海底捞最近的评价和槽点",
        "intent": ChatIntent.KNOWLEDGE_QUERY,
        "constraints": ChatConstraints(),
    }

    assert ClarificationPlanner().plan(state).needed is False
    assert route_after_constraints(state) == "hybrid_retrieve"


def test_structured_model_output_is_validated_and_used() -> None:
    intent_model = StructuredModel({"intent": "tool_use", "confidence": 0.9})
    constraint_model = StructuredModel(
        {
            "distance_meter_lte": 800,
            "budget_cent_per_person_lte": 9000,
            "cuisines": ["粤菜"],
            "party_size": 3,
            "open_now": True,
        }
    )

    assert IntentRouter(intent_model).classify("帮我处理一下") is ChatIntent.TOOL_USE
    assert ConstraintExtractor(constraint_model).extract("条件见上文") == ChatConstraints(
        distance_meter_lte=800,
        budget_cent_per_person_lte=9000,
        cuisines=("粤菜",),
        party_size=3,
        open_now=True,
    )
    assert intent_model.tasks == ["route_intent"]
    assert constraint_model.tasks == ["extract_constraints"]


def test_invalid_or_low_confidence_model_output_falls_back_to_rules() -> None:
    invalid = StructuredModel({"intent": "not-an-intent", "confidence": 1.0})
    low_confidence = StructuredModel({"intent": "general_chat", "confidence": 0.2})

    assert IntentRouter(invalid).classify("推荐川菜") is ChatIntent.KNOWLEDGE_QUERY
    assert IntentRouter(low_confidence).classify("总结这家店的评价") is ChatIntent.KNOWLEDGE_QUERY


def test_conditional_intent_routes_match_graph_design() -> None:
    base = {"conversation_id": "conversation-1", "user_query": "hello"}

    assert route_after_intent({**base, "intent": ChatIntent.GENERAL_CHAT}) == "generate_general"
    assert route_after_intent({**base, "intent": ChatIntent.TOOL_USE}) == "tool_guard"
    assert (
        route_after_intent({**base, "intent": ChatIntent.KNOWLEDGE_QUERY}) == "extract_constraints"
    )


def test_beverage_intent_patterns_route_to_knowledge_query() -> None:
    router = IntentRouter()

    # Intent verbs: want-to-drink patterns
    assert router.classify("\u6211\u60f3\u559d\u5976\u8336") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("\u60f3\u559d\u70b9\u4ec0\u4e48") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("\u60f3\u996e\u4e00\u676f\u5496\u5561") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("\u559d\u4ec0\u4e48\u6bd4\u8f83\u597d") is ChatIntent.KNOWLEDGE_QUERY

    # Category nouns (bare entity fallback)
    assert router.classify("\u996e\u54c1") is ChatIntent.KNOWLEDGE_QUERY
    assert router.classify("\u996e\u6599") is ChatIntent.KNOWLEDGE_QUERY
    assert (
        router.classify("\u9644\u8fd1\u6709\u4ec0\u4e48\u996e\u54c1\u5e97")
        is ChatIntent.KNOWLEDGE_QUERY
    )

    # Still general chat for unrelated input
    assert router.classify("\u4f60\u597d") is ChatIntent.GENERAL_CHAT
    assert router.classify("\u4eca\u5929\u5929\u6c14\u600e\u4e48\u6837") is ChatIntent.GENERAL_CHAT


def test_noodle_cuisine_aliases_are_extracted() -> None:
    """面, 面条, 拉面, 面馆 all map to 面食."""
    e = ConstraintExtractor()

    assert e.extract("我想吃面").cuisines == ("面食",)
    assert e.extract("附近有什么面条").cuisines == ("面食",)
    assert e.extract("推荐一家面馆").cuisines == ("面食",)
    assert e.extract("来碗拉面").cuisines == ("面食",)


def test_new_cuisine_replaces_old_not_accumulates() -> None:
    """A new cuisine mention replaces previously persisted cuisines."""
    e = ConstraintExtractor()

    result = e.extract(
        "我想吃面",
        existing=ChatConstraints(cuisines=("海鲜",)),
    )
    assert result.cuisines == ("面食",)


def test_empty_cuisine_query_retains_old_cuisines() -> None:
    """Follow-up without cuisine mention keeps old cuisines."""
    e = ConstraintExtractor()

    result = e.extract(
        "人均 50 元以内",
        existing=ChatConstraints(cuisines=("海鲜",), atmospheres=("安静",)),
    )
    assert result.cuisines == ("海鲜",)
    assert result.budget_cent_per_person_lte == 5000
    assert result.atmospheres == ("安静",)


def test_new_atmosphere_replaces_old() -> None:
    """A new atmosphere mention replaces previously persisted atmospheres."""
    e = ConstraintExtractor()

    result = e.extract(
        "找个热闹的地方",
        existing=ChatConstraints(atmospheres=("安静",)),
    )
    assert result.atmospheres == ("热闹",)
    # old atmosphere cleared, new one set


def test_atmosphere_retained_when_query_has_none() -> None:
    """Follow-up without atmosphere keeps old."""
    e = ConstraintExtractor()

    result = e.extract(
        "人均 30 元",
        existing=ChatConstraints(atmospheres=("浪漫",)),
    )
    assert result.atmospheres == ("浪漫",)


def test_empty_tuple_keeps_base_for_scenes_too() -> None:
    """The replace-not-union logic applies to scenes as well."""
    e = ConstraintExtractor()

    result = e.extract(
        "适合约会",
        existing=ChatConstraints(scenes=("聚会",)),
    )
    assert result.scenes == ("约会",)
