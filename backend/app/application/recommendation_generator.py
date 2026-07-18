"""Business recommendation generation with evidence linking.

Provides rule-based recommendation generation for merchant operations advice.
Each recommendation is backed by original review evidence and includes a
confidence score derived from data volume and supporting evidence count.

The engine analyses sentiment statistics (aspect-level positive rates, negative
reason aggregation) and produces structured recommendations in three
categories:

- ``negative_reason`` – actionable improvement for a specific complaint type
- ``weak_aspect``     – improvement for a low-rated aspect
- ``strength``       – reinforcement to maintain a high-rated aspect
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.infrastructure.db.models.sentiment import ReviewAnalysis

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------

PROMPT_VERSION = "v1.0-template"

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Evidence:
    """A single original review that supports a recommendation."""

    review_id: str
    review_text: str
    sentiment: str
    aspect_labels: list[str]
    negative_reasons: list[str]
    review_date: str | None


@dataclass
class Recommendation:
    """A single business recommendation with supporting evidence."""

    recommendation_id: str
    category: str  # "negative_reason" | "weak_aspect" | "strength"
    priority: str  # "high" | "medium" | "low"
    title: str
    description: str
    related_aspect: str | None
    related_negative_reason: str | None
    confidence: float
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class RecommendationReport:
    """Full recommendation report for a merchant."""

    merchant_id: str
    model_version: str
    prompt_version: str
    generated_at: datetime
    evidence_review_ids: list[str]
    summary: dict
    recommendations: list[Recommendation]
    low_sample_warning: bool


# ---------------------------------------------------------------------------
# Recommendation templates
# ---------------------------------------------------------------------------

# Maps each negative reason code to (title, description)
_NEGATIVE_REASON_TEMPLATES: dict[str, tuple[str, str]] = {
    "taste_bad": (
        "改进菜品口味",
        "多位顾客反馈菜品口味不佳，建议后厨重新评估菜品配方与调味标准，"
        "邀请厨师试菜并收集反馈，重点改进被提及的菜品。",
    ),
    "taste_unbalanced": (
        "统一调味标准",
        "顾客反馈口味不均衡（过咸/过淡等），建议建立标准化调味流程，"
        "确保每份菜品口味一致，定期抽查出品质量。",
    ),
    "cold_food": (
        "加强菜品保温管理",
        "菜品温度不达标影响用餐体验，建议检查保温设备状态，"
        "优化出餐到上桌的传递流程，缩短等待时间。",
    ),
    "too_small": (
        "评估菜品分量标准",
        "顾客普遍认为分量不足，建议重新评估各菜品的分量标准，适当增加主食材用量，确保性价比合理。",
    ),
    "stale": (
        "加强食材新鲜度管控",
        "食材新鲜度被多次提及，建议优化采购周期与储存条件，建立食材先进先出制度，每日检查库存。",
    ),
    "spoiled": (
        "紧急排查食品安全",
        "出现变质食品反馈属于严重问题，建议立即全面排查供应链，"
        "加强入库检验与存储温控，必要时下架问题菜品。",
    ),
    "overpriced": (
        "优化性价比定位",
        "顾客认为价格偏高，建议重新评估菜品定价策略，"
        "推出套餐或优惠组合提升性价比感知，同时优化成本结构。",
    ),
    "false_discount": (
        "规范优惠活动管理",
        "顾客反馈优惠活动存在误导或虚假宣传，建议核实所有活动规则，"
        "确保宣传内容与实际执行一致，加强门店员工活动培训。",
    ),
    "dirty": (
        "加强卫生清洁管理",
        "卫生问题被多次反馈，建议增加日常清洁频次，"
        "建立卫生检查清单制度，重点清洁餐桌、地面与卫生间。",
    ),
    "loud": (
        "改善用餐环境噪音",
        "环境嘈杂影响用餐体验，建议增加隔音设施，调整背景音乐音量，合理规划座位间距降低干扰。",
    ),
    "no_seat": (
        "优化座位管理",
        "高峰期座位不足，建议优化候座流程，增加候座区设施，考虑预约系统分流高峰客流。",
    ),
    "slow_wait": (
        "缩短顾客等待时间",
        "等待时间过长是主要投诉点，建议优化出餐流程与备餐效率，"
        "增加高峰期人手配置，引入叫号系统管理客流。",
    ),
    "rude_staff": (
        "加强员工服务培训",
        "服务态度问题被多次反馈，建议开展全员服务培训，"
        "建立服务考核制度，将顾客满意度纳入员工绩效评估。",
    ),
    "wrong_order": (
        "减少上菜差错",
        "上错菜/漏单问题频发，建议加强点餐与出餐的核对流程，"
        "引入双重复核机制，确保订单准确无误后再出餐。",
    ),
    "no_parking": (
        "解决停车难问题",
        "停车不便影响顾客到店意愿，建议与周边停车场建立合作，"
        "提供停车指引或代客泊车服务，在高峰期增加临时车位。",
    ),
    "bad_pack": (
        "改进外卖包装质量",
        "外卖包装问题影响配送体验，建议更换更牢固的包装材料，"
        "加强打包环节检查，对易洒漏菜品使用密封罐装。",
    ),
    "equipment_broken": (
        "检修与更新店内设施",
        "设施故障影响顾客体验，建议定期巡检空调、WiFi等设备，"
        "建立维修响应机制，故障设备24小时内修复或更换。",
    ),
    "close_early": (
        "规范营业时间管理",
        "提前打烊引发顾客不满，建议严格按公布时间营业，"
        "加强店长对关店时间的管控，建立违规处罚机制。",
    ),
    "delivery_delay": (
        "优化配送时效管理",
        "配送超时影响口碑，建议优化配送流程，加强配送时效监控，与配送平台建立超时预警机制。",
    ),
}

# Maps each aspect code to (weak_title, weak_desc, strength_title, strength_desc)
_ASPECT_TEMPLATES: dict[str, tuple[str, str, str, str]] = {
    "taste": (
        "改进菜品口味",
        "菜品口味是顾客的主要关注点，当前好评率偏低，建议后厨全面复盘菜品配方。",
        "保持口味优势",
        "菜品口味获得顾客广泛认可，建议继续保持出品标准，定期试菜确保质量稳定。",
    ),
    "portion": (
        "调整菜品分量",
        "分量问题被顾客提及，建议重新评估菜品标准用量，确保性价比合理。",
        "保持分量优势",
        "菜品分量获得好评，建议继续保持现有标准，作为宣传亮点之一。",
    ),
    "price": (
        "优化定价策略",
        "价格方面好评率偏低，建议推出更多套餐组合，提升性价比感知。",
        "保持价格优势",
        "价格定位获得认可，建议继续保持，可在营销中突出性价比优势。",
    ),
    "freshness": (
        "加强食材新鲜度",
        "食材新鲜度需要提升，建议优化采购与储存流程，确保食材品质。",
        "保持新鲜度优势",
        "食材新鲜度获得好评，建议继续保持采购标准，作为品牌卖点。",
    ),
    "appearance": (
        "提升菜品卖相",
        "菜品卖相有待改进，建议优化摆盘与装盘方式，提升视觉吸引力。",
        "保持卖相优势",
        "菜品颜值获得好评，建议继续保持出品标准，适合在社交媒体宣传。",
    ),
    "variety": (
        "丰富菜品选择",
        "顾客希望更多选择，建议定期更新菜单，增加季节性或特色菜品。",
        "保持品种优势",
        "菜品丰富度获得认可，建议继续保持菜单多样性，定期推陈出新。",
    ),
    "space": (
        "改善用餐空间",
        "空间拥挤影响体验，建议合理规划座位布局，适当增加桌间距。",
        "保持空间优势",
        "用餐空间获得好评，建议继续保持现有布局，提供舒适用餐环境。",
    ),
    "quiet": (
        "改善环境噪音",
        "环境嘈杂被多次提及，建议增加隔音措施，调整背景音乐音量。",
        "保持环境安静优势",
        "安静舒适的用餐环境获得好评，建议继续保持，适合宣传为商务用餐场所。",
    ),
    "decoration": (
        "升级装修风格",
        "装修环境有待改善，建议评估升级方案，提升整体用餐氛围。",
        "保持装修风格优势",
        "装修风格获得好评，建议保持现有设计风格，定期维护更新。",
    ),
    "hygiene": (
        "加强卫生管理",
        "卫生情况需要改善，建议增加清洁频次，建立卫生检查制度。",
        "保持卫生优势",
        "卫生状况获得好评，建议继续保持清洁标准，作为品牌承诺。",
    ),
    "location": (
        "提升位置便利性",
        "位置不便影响客流，建议优化导航指引，加强与周边商户合作引流。",
        "保持位置优势",
        "位置便利获得好评，建议在宣传中突出交通便利性。",
    ),
    "seating": (
        "优化座位管理",
        "座位问题被提及，建议优化座位安排，高峰期合理调配。",
        "保持座位优势",
        "座位安排获得好评，建议继续保持现有管理水平。",
    ),
    "waiting_time": (
        "缩短等待时间",
        "等待时间过长影响体验，建议优化出餐效率与客流管理。",
        "保持快速出餐优势",
        "出餐速度获得好评，建议继续保持高效运营，作为服务亮点。",
    ),
    "attitude": (
        "加强服务态度培训",
        "服务态度是主要短板，建议开展服务培训，建立考核机制。",
        "保持服务态度优势",
        "服务态度获得广泛好评，建议继续保持培训标准，将优质服务作为品牌核心。",
    ),
    "efficiency": (
        "提升服务效率",
        "服务效率有待提升，建议优化流程与人员配置，减少等待。",
        "保持效率优势",
        "服务效率获得好评，建议继续保持，定期评估流程优化空间。",
    ),
    "parking": (
        "解决停车问题",
        "停车不便影响到店体验，建议与周边停车场合作，提供停车指引。",
        "保持停车便利优势",
        "停车便利获得好评，建议在宣传中突出停车优势。",
    ),
    "packing": (
        "改进打包质量",
        "打包质量需要提升，建议更换更牢固的包装材料，加强检查。",
        "保持打包质量优势",
        "打包质量获得好评，建议继续保持，确保外卖体验一致。",
    ),
    "discount": (
        "规范优惠活动",
        "优惠活动规则需更透明，建议确保宣传与执行一致，加强员工培训。",
        "保持优惠活动优势",
        "优惠活动获得好评，建议继续保持，在营销中突出性价比。",
    ),
    "set_meal": (
        "优化套餐设计",
        "套餐搭配需优化，建议根据顾客反馈调整套餐组合与定价。",
        "保持套餐优势",
        "套餐设计获得好评，建议继续保持，定期更新套餐内容。",
    ),
    "equipment": (
        "维护店内设施",
        "设施问题影响体验，建议定期巡检与维修，确保正常运行。",
        "保持设施优势",
        "店内设施获得好评，建议继续保持维护标准，定期更新。",
    ),
    "overall": (
        "全面提升整体体验",
        "整体体验好评率偏低，建议综合分析各维度短板，制定系统性改进计划。",
        "保持整体体验优势",
        "整体体验获得好评，建议继续保持运营标准，将好评作为口碑宣传素材。",
    ),
}

# Maps aspect code to Chinese label (reused from reply_generator for consistency)
_ASPECT_CN: dict[str, str] = {
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

# Maps negative reason code to Chinese label
_REASON_CN: dict[str, str] = {
    "taste_bad": "口味差",
    "taste_unbalanced": "口味不均",
    "cold_food": "菜品偏凉",
    "too_small": "分量不足",
    "stale": "食材不新鲜",
    "spoiled": "食品变质",
    "overpriced": "价格偏高",
    "false_discount": "虚假优惠",
    "dirty": "卫生差",
    "loud": "环境嘈杂",
    "no_seat": "无座位",
    "slow_wait": "等待过久",
    "rude_staff": "服务态度差",
    "wrong_order": "上菜差错",
    "no_parking": "停车困难",
    "bad_pack": "包装问题",
    "equipment_broken": "设施故障",
    "close_early": "提前打烊",
    "delivery_delay": "配送超时",
}

# Thresholds
_MIN_SAMPLE_FOR_RECOMMENDATION = 2  # min negative_reason count to generate recommendation
_MIN_SAMPLE_FOR_ASPECT = 3  # min total reviews for aspect to be considered
_WEAK_ASPECT_THRESHOLD = 0.5  # positive_rate below this → weak aspect
_STRENGTH_ASPECT_THRESHOLD = 0.8  # positive_rate above this → strength
_HIGH_PRIORITY_REASON_COUNT = 5  # count >= this → high priority
_HIGH_PRIORITY_ASPECT_RATE = 0.3  # rate below this → high priority
_LOW_SAMPLE_THRESHOLD = 10  # total reviews below this → low_sample_warning
_FULL_CONFIDENCE_REVIEWS = 30  # reviews at which data confidence = 1.0
_FULL_CONFIDENCE_EVIDENCE = 5  # evidence count at which evidence confidence = 1.0
_MAX_EVIDENCE_PER_RECOMMENDATION = 5


# ---------------------------------------------------------------------------
# Confidence calculation
# ---------------------------------------------------------------------------


def _data_confidence(total_reviews: int) -> float:
    """Confidence based on total review volume."""
    return min(1.0, total_reviews / _FULL_CONFIDENCE_REVIEWS)


def _evidence_confidence(evidence_count: int) -> float:
    """Confidence based on number of supporting evidence reviews."""
    return min(1.0, evidence_count / _FULL_CONFIDENCE_EVIDENCE)


def _recommendation_confidence(total_reviews: int, evidence_count: int) -> float:
    """Combined confidence score (0.0–1.0), rounded to 2 decimals."""
    return round(
        (_data_confidence(total_reviews) + _evidence_confidence(evidence_count)) / 2,
        2,
    )


# ---------------------------------------------------------------------------
# Evidence building
# ---------------------------------------------------------------------------


def _build_evidence(
    reviews: list[ReviewAnalysis],
    *,
    max_count: int = _MAX_EVIDENCE_PER_RECOMMENDATION,
) -> list[Evidence]:
    """Convert ReviewAnalysis ORM rows into Evidence dataclass instances."""
    evidence: list[Evidence] = []
    for row in reviews[:max_count]:
        evidence.append(
            Evidence(
                review_id=str(row.id),
                review_text=row.review_text,
                sentiment=row.sentiment,
                aspect_labels=_parse_json_list(row.aspect_labels),
                negative_reasons=_parse_json_list(row.negative_reasons),
                review_date=(row.review_date.isoformat() if row.review_date else None),
            )
        )
    return evidence


def _parse_json_list(value: str | list) -> list[str]:
    """Safely parse a JSON column that may already be a Python list."""
    if isinstance(value, list):
        return value
    import json

    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


# ---------------------------------------------------------------------------
# Recommendation generator
# ---------------------------------------------------------------------------


class RecommendationGenerator:
    """Generate business recommendations from sentiment analytics data.

    The generator is purely rule-based: it examines negative-reason
    aggregation, aspect sentiment statistics and drill-down reviews to
    produce structured recommendations with evidence and confidence scores.
    """

    def generate(
        self,
        *,
        merchant_id: str,
        negative_reason_stats: list[dict],
        aspect_stats: list[dict],
        summary_stats: dict,
        evidence_reviews: dict[str, list[ReviewAnalysis]],
        model_version: str = "unknown",
    ) -> RecommendationReport:
        """Generate a recommendation report.

        Args:
            merchant_id: Target merchant identifier.
            negative_reason_stats: Output of
                ``get_negative_reason_aggregation`` – list of
                ``{"reason": str, "count": int}``.
            aspect_stats: Output of ``get_aspect_sentiment_stats`` – list of
                ``{"aspect": str, "positive": int, "neutral": int,
                   "negative": int, "total": int, "positive_rate": float}``.
            summary_stats: ``{"positive": int, "neutral": int,
                "negative": int, "total": int}`` for the merchant.
            evidence_reviews: Pre-fetched reviews keyed by negative reason
                code, used as evidence for negative-reason recommendations.

        Returns:
            A :class:`RecommendationReport` with recommendations and evidence.
        """
        total_reviews = summary_stats.get("total", 0)
        positive = summary_stats.get("positive", 0)
        negative = summary_stats.get("negative", 0)
        positive_rate = round(positive / total_reviews, 2) if total_reviews > 0 else 0.0
        negative_rate = round(negative / total_reviews, 2) if total_reviews > 0 else 0.0

        recommendations: list[Recommendation] = []

        # 1. Negative-reason-driven recommendations
        for stat in negative_reason_stats:
            reason = stat["reason"]
            count = stat["count"]
            if count < _MIN_SAMPLE_FOR_RECOMMENDATION:
                continue

            template = _NEGATIVE_REASON_TEMPLATES.get(reason)
            if not template:
                continue

            title, description = template
            priority = "high" if count >= _HIGH_PRIORITY_REASON_COUNT else "medium"

            reviews = evidence_reviews.get(reason, [])
            evidence = _build_evidence(reviews)
            confidence = _recommendation_confidence(total_reviews, len(evidence))

            recommendations.append(
                Recommendation(
                    recommendation_id=f"neg_{reason}",
                    category="negative_reason",
                    priority=priority,
                    title=title,
                    description=description,
                    related_aspect=_reason_to_aspect(reason),
                    related_negative_reason=reason,
                    confidence=confidence,
                    evidence=evidence,
                )
            )

        # 2. Weak-aspect recommendations (positive_rate < 0.5, total >= 3)
        #    Skip aspects already covered by negative-reason recommendations
        covered_aspects = {r.related_aspect for r in recommendations if r.related_aspect}
        for stat in aspect_stats:
            aspect = stat["aspect"]
            total = stat["total"]
            positive_rate_val = stat["positive_rate"]

            if total < _MIN_SAMPLE_FOR_ASPECT:
                continue
            if positive_rate_val >= _WEAK_ASPECT_THRESHOLD:
                continue
            if aspect in covered_aspects:
                continue

            templates = _ASPECT_TEMPLATES.get(aspect)
            if not templates:
                continue

            title, description, _, _ = templates
            priority = "high" if positive_rate_val < _HIGH_PRIORITY_ASPECT_RATE else "medium"

            confidence = _recommendation_confidence(total_reviews, total)

            recommendations.append(
                Recommendation(
                    recommendation_id=f"weak_{aspect}",
                    category="weak_aspect",
                    priority=priority,
                    title=title,
                    description=description,
                    related_aspect=aspect,
                    related_negative_reason=None,
                    confidence=confidence,
                    evidence=[],  # no specific evidence linked for weak aspects
                )
            )

        # 3. Strength recommendations (positive_rate > 0.8, total >= 5)
        for stat in aspect_stats:
            aspect = stat["aspect"]
            total = stat["total"]
            positive_rate_val = stat["positive_rate"]

            if total < 5:
                continue
            if positive_rate_val <= _STRENGTH_ASPECT_THRESHOLD:
                continue

            templates = _ASPECT_TEMPLATES.get(aspect)
            if not templates:
                continue

            _, _, title, description = templates

            confidence = _recommendation_confidence(total_reviews, total)

            recommendations.append(
                Recommendation(
                    recommendation_id=f"strength_{aspect}",
                    category="strength",
                    priority="low",
                    title=title,
                    description=description,
                    related_aspect=aspect,
                    related_negative_reason=None,
                    confidence=confidence,
                    evidence=[],
                )
            )

        # Sort: high → medium → low, then by confidence descending
        priority_order = {"high": 0, "medium": 1, "low": 2}
        recommendations.sort(key=lambda r: (priority_order.get(r.priority, 3), -r.confidence))

        low_sample_warning = total_reviews < _LOW_SAMPLE_THRESHOLD

        # Collect all evidence review IDs (flat list for traceability)
        evidence_review_ids: list[str] = []
        for rec in recommendations:
            for ev in rec.evidence:
                if ev.review_id not in evidence_review_ids:
                    evidence_review_ids.append(ev.review_id)

        return RecommendationReport(
            merchant_id=merchant_id,
            model_version=model_version,
            prompt_version=PROMPT_VERSION,
            generated_at=datetime.now(tz=UTC),
            evidence_review_ids=evidence_review_ids,
            summary={
                "total_reviews": total_reviews,
                "positive": positive,
                "neutral": summary_stats.get("neutral", 0),
                "negative": negative,
                "positive_rate": positive_rate,
                "negative_rate": negative_rate,
                "data_confidence": round(_data_confidence(total_reviews), 2),
            },
            recommendations=recommendations,
            low_sample_warning=low_sample_warning,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reason_to_aspect(reason: str) -> str | None:
    """Map a negative reason code to its primary aspect code."""
    mapping = {
        "taste_bad": "taste",
        "taste_unbalanced": "taste",
        "cold_food": "overall",
        "too_small": "portion",
        "stale": "freshness",
        "spoiled": "freshness",
        "overpriced": "price",
        "false_discount": "discount",
        "dirty": "hygiene",
        "loud": "quiet",
        "no_seat": "seating",
        "slow_wait": "waiting_time",
        "rude_staff": "attitude",
        "wrong_order": "efficiency",
        "no_parking": "parking",
        "bad_pack": "packing",
        "equipment_broken": "equipment",
        "close_early": "overall",
        "delivery_delay": "efficiency",
    }
    return mapping.get(reason)


def get_aspect_label(aspect_code: str) -> str:
    """Return the Chinese label for an aspect code."""
    return _ASPECT_CN.get(aspect_code, aspect_code)


def get_reason_label(reason_code: str) -> str:
    """Return the Chinese label for a negative reason code."""
    return _REASON_CN.get(reason_code, reason_code)
