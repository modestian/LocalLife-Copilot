"""Review reply generation with compliance constraints.

Provides template-based reply generation for merchant responses to customer
reviews.  Templates are selected by sentiment and negative-reason category,
then validated against compliance rules that prohibit fabricated compensation
claims (fake refunds, unauthorised discounts, etc.).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.analytics.sentiment_classifier import AspectExtractor

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

PROMPT_VERSION = "v1.0-template"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReplyTemplate:
    """A single reply template keyed by sentiment + optional negative reason."""

    template_id: str
    sentiment: str
    negative_reason: str | None
    template: str


@dataclass
class ReplyResult:
    """Output of the reply generator."""

    reply_text: str
    template_id: str
    compliance_passed: bool
    model_version: str = "unknown"
    prompt_version: str = PROMPT_VERSION
    generated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    evidence_review_ids: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------

REPLY_TEMPLATES: list[ReplyTemplate] = [
    # --- POSITIVE ---
    ReplyTemplate(
        template_id="positive_default",
        sentiment="POSITIVE",
        negative_reason=None,
        template=("感谢您的好评！很高兴您对{aspects}感到满意，我们会继续保持，期待您下次光临。"),
    ),
    # --- NEUTRAL ---
    ReplyTemplate(
        template_id="neutral_default",
        sentiment="NEUTRAL",
        negative_reason=None,
        template=(
            "感谢您的反馈。关于{aspects}方面，"
            "我们会认真听取建议并持续改进，期待下次能给您更好的体验。"
        ),
    ),
    # --- NEGATIVE: specific reasons ---
    ReplyTemplate(
        template_id="neg_slow_wait",
        sentiment="NEGATIVE",
        negative_reason="slow_wait",
        template=(
            "非常抱歉让您久等了。我们已优化出餐流程，"
            "增加备餐人手，努力缩短等待时间。感谢您的耐心，期待下次给您更好的体验。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_rude_staff",
        sentiment="NEGATIVE",
        negative_reason="rude_staff",
        template=(
            "抱歉我们的服务让您感到不适。我们已加强员工服务培训，"
            "确保每位顾客都能感受到热情与尊重。感谢您的批评指正。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_taste_bad",
        sentiment="NEGATIVE",
        negative_reason="taste_bad",
        template=(
            "抱歉口味未能达到您的期望。我们已将您的反馈转达后厨，"
            "认真改进菜品味道，希望下次能让您满意。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_taste_unbalanced",
        sentiment="NEGATIVE",
        negative_reason="taste_unbalanced",
        template=(
            "感谢您对口味的反馈。我们已调整 seasoning 标准，确保口味更加均衡，期待您再次品尝。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_cold_food",
        sentiment="NEGATIVE",
        negative_reason="cold_food",
        template=(
            "抱歉菜品温度未达标。我们已检查保温设备并加强出餐温度管控，"
            "确保每位顾客都能享用到热乎的菜品。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_too_small",
        sentiment="NEGATIVE",
        negative_reason="too_small",
        template=(
            "感谢您对分量的反馈。我们已重新评估菜品标准，适当调整份量，努力让每位顾客吃得满意。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_overpriced",
        sentiment="NEGATIVE",
        negative_reason="overpriced",
        template=(
            "感谢您对价格的建议。我们会持续优化性价比，提供更实惠的菜品选择，期待您的再次光临。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_dirty",
        sentiment="NEGATIVE",
        negative_reason="dirty",
        template=(
            "抱歉卫生情况让您不满。我们已加强清洁流程，增加卫生检查频次，确保用餐环境干净整洁。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_loud",
        sentiment="NEGATIVE",
        negative_reason="loud",
        template=(
            "抱歉环境嘈杂影响了您的用餐体验。我们已增加隔音措施，"
            "调整店内音乐音量，努力营造更舒适的氛围。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_wrong_order",
        sentiment="NEGATIVE",
        negative_reason="wrong_order",
        template=(
            "非常抱歉上错菜品。我们已加强点餐与出餐的核对流程，确保订单准确无误，感谢您的理解。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_stale",
        sentiment="NEGATIVE",
        negative_reason="stale",
        template=(
            "抱歉食材新鲜度未达标。我们已严格把控食材采购与储存，加强新鲜度检查，确保食品安全。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_spoiled",
        sentiment="NEGATIVE",
        negative_reason="spoiled",
        template=(
            "对此我们深表歉意。食品安全是我们最重视的问题，"
            "我们已全面排查供应链并加强质量检测，"
            "确保类似问题不再发生。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_no_seat",
        sentiment="NEGATIVE",
        negative_reason="no_seat",
        template=("抱歉等位时间过长。我们已优化座位管理流程，增加候座区域，努力减少您的等待。"),
    ),
    ReplyTemplate(
        template_id="neg_no_parking",
        sentiment="NEGATIVE",
        negative_reason="no_parking",
        template=(
            "感谢您对停车的反馈。我们已与周边停车场建立合作，努力为顾客提供更便利的停车选择。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_bad_pack",
        sentiment="NEGATIVE",
        negative_reason="bad_pack",
        template=(
            "抱歉外包装出现了问题。我们已更换更牢固的包装材料，"
            "加强打包环节的检查，确保菜品完好送达。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_equipment_broken",
        sentiment="NEGATIVE",
        negative_reason="equipment_broken",
        template=("抱歉设施问题影响了您的体验。我们已安排检修并更新设备，确保店内设施正常运行。"),
    ),
    ReplyTemplate(
        template_id="neg_close_early",
        sentiment="NEGATIVE",
        negative_reason="close_early",
        template=(
            "抱歉给您带来不便。我们已调整营业时间管理，确保严格按照公布时间营业，感谢您的理解。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_delivery_delay",
        sentiment="NEGATIVE",
        negative_reason="delivery_delay",
        template=(
            "抱歉配送超时。我们已优化配送流程并加强时效管理，努力确保准时送达，感谢您的耐心。"
        ),
    ),
    ReplyTemplate(
        template_id="neg_false_discount",
        sentiment="NEGATIVE",
        negative_reason="false_discount",
        template=(
            "感谢您的反馈。我们已核实活动信息，加强优惠规则的透明度管理，确保宣传内容准确无误。"
        ),
    ),
    # --- NEGATIVE: fallback ---
    ReplyTemplate(
        template_id="negative_default",
        sentiment="NEGATIVE",
        negative_reason=None,
        template=(
            "非常抱歉给您带来了不好的体验。我们已记录您的反馈，"
            "会认真改进{aspects}方面的问题，期待下次能给您更好的服务。"
        ),
    ),
]

_TEMPLATE_INDEX: dict[tuple[str, str | None], ReplyTemplate] = {}


def _build_index() -> None:
    for tpl in REPLY_TEMPLATES:
        key = (tpl.sentiment, tpl.negative_reason)
        _TEMPLATE_INDEX[key] = tpl


_build_index()

_ASPECT_LABEL_MAP: dict[str, str] = {
    "taste": "口味",
    "portion": "分量",
    "price": "价格",
    "freshness": "新鲜度",
    "appearance": "卖相",
    "variety": "品种",
    "space": "空间",
    "quiet": "环境安静度",
    "decoration": "装修环境",
    "hygiene": "卫生",
    "location": "位置",
    "seating": "座位",
    "waiting_time": "等待时间",
    "attitude": "服务态度",
    "efficiency": "效率",
    "parking": "停车",
    "packing": "打包",
    "discount": "优惠",
    "set_meal": "套餐",
    "equipment": "设施",
    "overall": "整体体验",
}


def _aspects_to_chinese(aspects: list[str]) -> str:
    """Convert aspect codes to a human-readable Chinese string."""
    labels = [_ASPECT_LABEL_MAP.get(a, a) for a in aspects]
    return "、".join(labels) if labels else "服务"


# ---------------------------------------------------------------------------
# Compliance rules
# ---------------------------------------------------------------------------

# Patterns that indicate fabricated or unauthorised compensation claims.
# Each entry: (pattern, violation_description)
_COMPLIANCE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Specific refund amounts
    (re.compile(r"退款\s*\d+\s*元"), "提及具体退款金额"),
    (re.compile(r"退您\s*\d+"), "提及具体退款金额"),
    (re.compile(r"退还\s*\d+"), "提及具体退款金额"),
    # Discount promises
    (re.compile(r"\d+\s*折"), "承诺折扣优惠"),
    (re.compile(r"满\s*\d+\s*减"), "承诺满减优惠"),
    (re.compile(r"免\s*单"), "承诺免单"),
    # Fabricated compensation
    (re.compile(r"已为您.*(?:发放|赠送|发送).*(?:券|优惠)"), "虚构优惠券发放"),
    (re.compile(r"已.*退款"), "声称已退款"),
    (re.compile(r"已.*补偿"), "声称已补偿"),
    (re.compile(r"赠送.*(?:菜品|礼品)"), "承诺赠送物品"),
    # Responsibility deflection
    (re.compile(r"第三方.*(?:责任|问题)"), "推卸责任给第三方"),
    (re.compile(r"与我们(?:无关|没有关系)"), "推卸责任"),
    (re.compile(r"不是我们.*(?:责任|问题)"), "推卸责任"),
    (re.compile(r"非我们.*(?:责任|问题)"), "推卸责任"),
]


def check_compliance(text: str) -> list[str]:
    """Return a list of compliance violation descriptions (empty if compliant)."""
    violations: list[str] = []
    for pattern, description in _COMPLIANCE_PATTERNS:
        if pattern.search(text):
            violations.append(description)
    return violations


# ---------------------------------------------------------------------------
# Reply generator
# ---------------------------------------------------------------------------


class ReplyGenerator:
    """Generate compliant review replies from sentiment analysis results."""

    def generate(
        self,
        *,
        review_text: str,
        sentiment: str,
        aspect_labels: list[str] | None = None,
        negative_reasons: list[str] | None = None,
        review_id: str | None = None,
        model_version: str = "unknown",
    ) -> ReplyResult:
        """Generate a review reply.

        Args:
            review_text: Original review text (used for aspect extraction
                when aspect_labels is empty).
            sentiment: One of POSITIVE / NEUTRAL / NEGATIVE.
            aspect_labels: Aspect codes from sentiment analysis.
            negative_reasons: Negative reason codes (only for NEGATIVE).
            review_id: Original review ID for traceability.
            model_version: Sentiment model version for traceability.

        Returns:
            ReplyResult with reply_text, template_id, compliance status,
            and traceability fields (model_version, prompt_version,
            generated_at, evidence_review_ids).
        """
        aspects = list(aspect_labels) if aspect_labels else []
        if not aspects and review_text:
            aspects = AspectExtractor.extract_aspects(review_text)

        reasons = list(negative_reasons) if negative_reasons else []
        template = self._select_template(sentiment, reasons)
        reply_text = self._fill_template(template, aspects)

        violations = check_compliance(reply_text)
        return ReplyResult(
            reply_text=reply_text,
            template_id=template.template_id,
            compliance_passed=len(violations) == 0,
            model_version=model_version,
            prompt_version=PROMPT_VERSION,
            evidence_review_ids=[review_id] if review_id else [],
            violations=violations,
        )

    def _select_template(self, sentiment: str, negative_reasons: list[str]) -> ReplyTemplate:
        """Select the best-matching template for the given inputs."""
        # Try specific negative reason first
        for reason in negative_reasons:
            key = (sentiment, reason)
            if key in _TEMPLATE_INDEX:
                return _TEMPLATE_INDEX[key]
        # Fall back to sentiment-only template
        key = (sentiment, None)
        if key in _TEMPLATE_INDEX:
            return _TEMPLATE_INDEX[key]
        # Ultimate fallback
        return ReplyTemplate(
            template_id="fallback",
            sentiment=sentiment,
            negative_reason=None,
            template="感谢您的反馈，我们会认真改进，期待下次为您服务。",
        )

    def _fill_template(self, template: ReplyTemplate, aspects: list[str]) -> str:
        """Fill template placeholders with aspect labels."""
        aspect_str = _aspects_to_chinese(aspects)
        return template.template.replace("{aspects}", aspect_str)
