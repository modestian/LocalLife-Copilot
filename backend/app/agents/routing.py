"""Intent routing, constraint extraction and clarification nodes for the chat graph."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, fields, replace
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.contracts import ModelAdapter, ModelInput, NodeContract, StateUpdate
from app.agents.state import ChatState, StateField
from app.agents.types import ChatConstraints, ChatIntent


class IntentOutput(BaseModel):
    """Validated structured output accepted from an intent model."""

    model_config = ConfigDict(extra="forbid")
    intent: ChatIntent
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ConstraintOutput(BaseModel):
    """Validated incremental constraints accepted from an extraction model."""

    model_config = ConfigDict(extra="forbid")
    distance_meter_lte: int | None = Field(default=None, gt=0)
    budget_cent_per_person_lte: int | None = Field(default=None, gt=0)
    cuisines: tuple[str, ...] = ()
    atmospheres: tuple[str, ...] = ()
    scenes: tuple[str, ...] = ()
    party_size: int | None = Field(default=None, gt=0)
    open_now: bool | None = None

    def to_constraints(self) -> ChatConstraints:
        return ChatConstraints(**self.model_dump())


@dataclass(frozen=True, slots=True)
class ClarificationDecision:
    needed: bool
    missing_fields: tuple[str, ...] = ()
    question: str | None = None


ROUTE_INTENT_CONTRACT = NodeContract(
    name="route_intent",
    requires=frozenset({StateField.USER_QUERY}),
    produces=frozenset({StateField.INTENT}),
)
EXTRACT_CONSTRAINTS_CONTRACT = NodeContract(
    name="extract_constraints",
    requires=frozenset({StateField.USER_QUERY, StateField.INTENT}),
    produces=frozenset({StateField.CONSTRAINTS}),
)
ASK_QUESTION_CONTRACT = NodeContract(
    name="ask_question",
    requires=frozenset({StateField.USER_QUERY, StateField.INTENT, StateField.CONSTRAINTS}),
    produces=frozenset({StateField.ANSWER}),
)

_TOOL_MARKERS = ("调用工具", "使用工具", "运行工具", "tool call", "tool_call")
_KNOWLEDGE_MARKERS = (
    "推荐",
    "探店",
    "找店",
    "找一家",
    "搜一下",
    "哪里吃",
    "吃什么",
    "餐厅",
    "饭店",
    "馆子",
    "菜馆",
    "面馆",
    "火锅店",
    "烧烤店",
    "咖啡店",
    "奶茶店",
    "小吃",
    "外卖",
    "食堂",
    "评价",
    "评论",
    "点评",
    "口碑",
    "差评",
    "好评",
    "评分",
    "打分",
    "星级",
    "槽点",
    "亮点",
    "值得去",
    "踩雷",
    "人均",
    "预算",
    "公里",
    "千米",
    "附近",
    "周边",
    "步行",
    "骑车",
    "好吃",
    "难吃",
    "服务好",
    "态度差",
    "环境好",
    "性价比",
    "划算",
    "实惠",
    "安静",
    "热闹",
    "排队",
    "等位",
    "预约",
    "订座",
    "包厢",
    "停车",
)
_REVIEW_MARKERS = (
    "评价",
    "评论",
    "点评",
    "口碑",
    "亮点",
    "槽点",
    "差评",
    "好评",
    "评分",
    "打分",
    "星级",
    "值得去",
)
_RECOMMENDATION_MARKERS = (
    "推荐",
    "探店",
    "找店",
    "找一家",
    "搜一下",
    "哪里吃",
    "吃什么",
    "餐厅",
    "饭店",
    "馆子",
    "菜馆",
    "面馆",
    "火锅店",
    "烧烤店",
    "咖啡店",
    "奶茶店",
    "小吃",
    "外卖",
    "食堂",
    "附近",
    "周边",
    "步行",
    "骑车",
    "好吃",
    "难吃",
    "服务好",
    "态度差",
    "环境好",
    "性价比",
    "划算",
    "实惠",
    "安静",
    "热闹",
    "排队",
    "等位",
    "预约",
    "订座",
    "包厢",
    "停车",
)
_FOLLOW_UP_MARKERS = (
    "再来",
    "还有",
    "换一家",
    "换一个",
    "换个",
    "继续",
    "另外",
    "其他",
    "这家",
    "那家",
    "它",
    "刚才",
    "前面",
)
_EXPLORATION_CONTEXT_MARKER = "[探店条件]"

_CUISINE_ALIASES: Mapping[str, str] = {
    "川菜": "川菜",
    "四川菜": "川菜",
    "火锅": "火锅",
    "粤菜": "粤菜",
    "广东菜": "粤菜",
    "湘菜": "湘菜",
    "湖南菜": "湘菜",
    "鲁菜": "鲁菜",
    "江浙菜": "江浙菜",
    "本帮菜": "本帮菜",
    "日料": "日本料理",
    "日本料理": "日本料理",
    "寿司": "日本料理",
    "韩餐": "韩国料理",
    "韩国料理": "韩国料理",
    "西餐": "西餐",
    "意大利菜": "意大利菜",
    "泰国菜": "泰国菜",
    "烧烤": "烧烤",
    "烤肉": "烤肉",
    "海鲜": "海鲜",
    "素食": "素食",
    "咖啡": "咖啡",
    "甜品": "甜品",
}
_ATMOSPHERE_ALIASES: Mapping[str, str] = {
    "安静": "安静",
    "清静": "安静",
    "热闹": "热闹",
    "浪漫": "浪漫",
    "有氛围": "有氛围",
    "氛围感": "有氛围",
    "复古": "复古",
    "文艺": "文艺",
    "私密": "私密",
    "高档": "高档",
    "休闲": "休闲",
}
_SCENE_ALIASES: Mapping[str, str] = {
    "约会": "约会",
    "聚会": "聚会",
    "团建": "团建",
    "商务宴请": "商务宴请",
    "谈事": "商务会谈",
    "商务会谈": "商务会谈",
    "亲子": "亲子",
    "带娃": "亲子",
    "家庭聚餐": "家庭聚餐",
    "独食": "独食",
    "一个人吃": "独食",
    "下午茶": "下午茶",
    "夜宵": "夜宵",
}
_CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


class IntentRouter:
    """Route a turn to one of three graph intents, with deterministic fallback."""

    def __init__(self, model: ModelAdapter | None = None, *, confidence_threshold: float = 0.6):
        self._model = model
        self._confidence_threshold = confidence_threshold

    def classify(
        self,
        query: str,
        *,
        history_summary: str | None = None,
        existing_constraints: ChatConstraints | None = None,
    ) -> ChatIntent:
        normalized = query.strip()
        if not normalized:
            return ChatIntent.GENERAL_CHAT
        output = self._predict(normalized, history_summary)
        if output is not None and output.confidence >= self._confidence_threshold:
            return output.intent
        return _rule_based_intent(normalized, history_summary, existing_constraints)

    def __call__(self, state: ChatState) -> StateUpdate:
        return {
            "intent": self.classify(
                state["user_query"],
                history_summary=state.get("history_summary"),
                existing_constraints=state.get("constraints"),
            )
        }

    def _predict(self, query: str, history_summary: str | None) -> IntentOutput | None:
        if self._model is None:
            return None
        prompt = (
            "将输入分类为 knowledge_query、tool_use 或 general_chat。探店和评价摘要属于"
            " knowledge_query；只有明确要求调用工具才属于 tool_use。"
            f"\n历史摘要：{history_summary or '无'}\n用户输入：{query}"
        )
        try:
            result = _validated_prediction(
                self._model.predict((ModelInput(task="route_intent", prompt=prompt),)), IntentOutput
            )
            return result if isinstance(result, IntentOutput) else None
        except (RuntimeError, TypeError, ValueError):
            return None


class ClarificationPlanner:
    """Ask recommendation turns for missing budget and party size."""

    def plan(self, state: ChatState) -> ClarificationDecision:
        if state.get("intent") is not ChatIntent.KNOWLEDGE_QUERY:
            return ClarificationDecision(False)
        context = " ".join(
            value for value in (state.get("history_summary"), state["user_query"]) if value
        )
        if not _is_recommendation_request(context):
            return ClarificationDecision(False)
        constraints = state.get("constraints", ChatConstraints())
        missing: list[str] = []
        if constraints.budget_cent_per_person_lte is None:
            missing.append("budget_cent_per_person_lte")
        if constraints.party_size is None:
            missing.append("party_size")
        if not missing:
            return ClarificationDecision(False)
        labels = {"budget_cent_per_person_lte": "人均预算", "party_size": "用餐人数"}
        examples = []
        if "budget_cent_per_person_lte" in missing:
            examples.append("人均 100 元以内")
        if "party_size" in missing:
            examples.append("2 人")
        return ClarificationDecision(
            True,
            tuple(missing),
            "为了给你更合适的推荐，请补充"
            + "和".join(labels[item] for item in missing)
            + f"（例如：{'，'.join(examples)}）。",
        )

    def __call__(self, state: ChatState) -> StateUpdate:
        decision = self.plan(state)
        return {"answer": decision.question} if decision.needed else {}


def route_after_intent(state: ChatState) -> str:
    return {
        ChatIntent.GENERAL_CHAT: "generate_general",
        ChatIntent.TOOL_USE: "tool_guard",
        ChatIntent.KNOWLEDGE_QUERY: "extract_constraints",
    }.get(state.get("intent"), "generate_general")


def route_after_constraints(state: ChatState) -> str:
    return "ask_question" if ClarificationPlanner().plan(state).needed else "hybrid_retrieve"


def merge_constraints(base: ChatConstraints, patch: ChatConstraints) -> ChatConstraints:
    """Overlay populated scalar fields and union ordered multi-value fields."""
    updates: dict[str, Any] = {}
    for item in fields(ChatConstraints):
        name = item.name
        value = getattr(patch, name)
        if name in {"cuisines", "atmospheres", "scenes"}:
            updates[name] = _ordered_unique((*getattr(base, name), *value))
        elif value is not None:
            updates[name] = value
    return replace(base, **updates)


def _user_constraint_history(history_summary: str | None) -> str | None:
    """Keep only explicit user filter blocks when rebuilding retained constraints."""
    if not history_summary:
        return None
    markers = re.compile(r"(?:用户：|待确认：|USER:|ASSISTANT:|SYSTEM:|TOOL:)")
    matches = tuple(markers.finditer(history_summary))
    user_parts: list[str] = []
    for index, match in enumerate(matches):
        marker = match.group()
        if marker not in {"用户：", "USER:"}:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(history_summary)
        content = history_summary[match.end() : end].strip()
        marker_start = content.find(_EXPLORATION_CONTEXT_MARKER)
        if marker_start >= 0:
            user_parts.append(content[marker_start:])
    return "\n".join(user_parts) or None


def _rule_based_intent(
    query: str,
    history_summary: str | None,
    existing_constraints: ChatConstraints | None,
) -> ChatIntent:
    lowered = query.casefold()
    if any(marker in lowered for marker in _TOOL_MARKERS) or re.search(
        r"(?:调用|使用|运行)[\w\u4e00-\u9fff]{0,20}(?:地图|天气|导航|计算器)", query
    ):
        return ChatIntent.TOOL_USE
    if any(marker in lowered for marker in _KNOWLEDGE_MARKERS):
        return ChatIntent.KNOWLEDGE_QUERY
    if _has_explicit_constraint(query):
        return ChatIntent.KNOWLEDGE_QUERY
    if (
        history_summary
        and any(marker in query for marker in _FOLLOW_UP_MARKERS)
        and _is_recommendation_request(history_summary)
    ):
        return ChatIntent.KNOWLEDGE_QUERY
    return ChatIntent.GENERAL_CHAT


def _rule_based_constraints(text: str) -> ChatConstraints:
    return ChatConstraints(
        distance_meter_lte=_extract_distance(text),
        budget_cent_per_person_lte=_extract_budget(text),
        cuisines=_extract_aliases(text, _CUISINE_ALIASES),
        atmospheres=_extract_aliases(text, _ATMOSPHERE_ALIASES),
        scenes=_extract_aliases(text, _SCENE_ALIASES),
        party_size=_extract_party_size(text),
        open_now=_extract_open_now(text),
    )


def _extract_distance(text: str) -> int | None:
    matches = re.findall(r"(\d+(?:\.\d+)?)\s*(公里|千米|km|KM|米|m)(?:以内|内|范围内|之内)?", text)
    if not matches:
        return 1000 if "附近" in text else None
    values = [
        round(float(number) * (1000 if unit.casefold() in {"公里", "千米", "km"} else 1))
        for number, unit in matches
    ]
    return min(value for value in values if value > 0)


def _extract_budget(text: str) -> int | None:
    patterns = (
        r"(?:人均|每人|预算)\s*(?:约|大概|不超过|不高于|最多|控制在)?\s*[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?(?:以内|以下|左右|封顶)?",
        r"[¥￥]\s*(\d+(?:\.\d+)?)\s*(?:以内|以下|左右|封顶)",
        r"(\d+(?:\.\d+)?)\s*(?:元|块)\s*(?:以内|以下|封顶)",
    )
    for pattern in patterns:
        if match := re.search(pattern, text):
            amount = round(float(match.group(1)) * 100)
            return amount if amount > 0 else None
    return None


def _extract_party_size(text: str) -> int | None:
    if match := re.search(r"(?<!人均)(\d{1,3})\s*(?:人|位)(?:用餐|吃饭)?", text):
        value = int(match.group(1))
        return value if value > 0 else None
    if match := re.search(r"([一二两三四五六七八九十])\s*(?:个)?(?:人|位)", text):
        return _CHINESE_DIGITS[match.group(1)]
    if "独食" in text or "一个人" in text:
        return 1
    return None


def _extract_open_now(text: str) -> bool | None:
    if re.search(r"(?:不用|不必|无需).{0,4}(?:现在)?营业", text):
        return None
    if re.search(r"现在.{0,4}(?:营业|开门|开着)|(?:当前|正在|仍在|还在)营业|营业中", text):
        return True
    return None


def _extract_aliases(text: str, aliases: Mapping[str, str]) -> tuple[str, ...]:
    return _ordered_unique(value for marker, value in aliases.items() if marker in text)


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _is_recommendation_request(text: str) -> bool:
    if any(marker in text for marker in _REVIEW_MARKERS) and not any(
        marker in text for marker in _RECOMMENDATION_MARKERS
    ):
        return False
    return any(marker in text for marker in _RECOMMENDATION_MARKERS)


def _has_explicit_constraint(text: str) -> bool:
    return _has_any_constraint(_rule_based_constraints(text))


def _has_any_constraint(constraints: ChatConstraints) -> bool:
    return any(
        (
            constraints.distance_meter_lte,
            constraints.budget_cent_per_person_lte,
            constraints.cuisines,
            constraints.atmospheres,
            constraints.scenes,
            constraints.party_size,
            constraints.open_now,
        )
    )


def _validated_prediction(
    predictions: Sequence[Any], schema: type[IntentOutput] | type[ConstraintOutput]
) -> IntentOutput | ConstraintOutput | None:
    if len(predictions) != 1:
        return None
    prediction = predictions[0]
    payload = prediction.structured
    if payload is None:
        try:
            payload = json.loads(prediction.text)
        except (json.JSONDecodeError, TypeError):
            return None
    try:
        return schema.model_validate(payload)
    except ValidationError:
        return None


class ConstraintExtractor:
    """Extract this turn's constraints and merge them with retained context."""

    def __init__(self, model: ModelAdapter | None = None):
        self._model = model

    def extract(
        self,
        query: str,
        *,
        existing: ChatConstraints | None = None,
        history_summary: str | None = None,
    ) -> ChatConstraints:
        user_history = _user_constraint_history(history_summary)
        result = ChatConstraints()
        if user_history:
            result = merge_constraints(result, _rule_based_constraints(user_history))
        elif existing is not None:
            result = merge_constraints(result, existing)
        patch = _rule_based_constraints(query)
        if model_patch := self._predict(query, user_history):
            patch = merge_constraints(patch, model_patch.to_constraints())
        return merge_constraints(result, patch)

    def __call__(self, state: ChatState) -> StateUpdate:
        if state.get("intent") is not ChatIntent.KNOWLEDGE_QUERY:
            return {"constraints": state.get("constraints", ChatConstraints())}
        return {
            "constraints": self.extract(
                state["user_query"],
                existing=state.get("constraints"),
                history_summary=state.get("history_summary"),
            )
        }

    def _predict(self, query: str, history_summary: str | None) -> ConstraintOutput | None:
        if self._model is None:
            return None
        prompt = (
            "抽取本轮明确表达的本地生活检索约束。距离统一为米，人均预算统一为分；"
            f"不要猜测未提供字段。\n历史摘要：{history_summary or '无'}\n用户输入：{query}"
        )
        try:
            result = _validated_prediction(
                self._model.predict((ModelInput(task="extract_constraints", prompt=prompt),)),
                ConstraintOutput,
            )
            return result if isinstance(result, ConstraintOutput) else None
        except (RuntimeError, TypeError, ValueError):
            return None
