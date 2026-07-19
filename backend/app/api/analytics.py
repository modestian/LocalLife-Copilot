"""Sentiment analytics REST endpoints."""

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.api.dependencies.authorization import (
    CurrentPrincipal,
    require_permission,
    require_query_resource_access,
    require_resource_access,
)
from app.application.analytics import AnalyticsService
from app.application.authorization import ResourceType
from app.application.reply_generator import ReplyGenerator
from app.core.api import success_response
from app.core.errors import AppError

merchant_read_dependency = require_resource_access(
    ResourceType.MERCHANT,
    "READ",
    path_parameter="merchant_id",
)
merchant_compare_dependency = require_query_resource_access(
    ResourceType.MERCHANT,
    "READ",
    query_parameter="merchant_ids",
)

router = APIRouter(
    prefix="/merchants/{merchant_id}/analytics",
    tags=["analytics"],
    dependencies=[Depends(merchant_read_dependency)],
)
compare_router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[Depends(merchant_compare_dependency)],
)
business_router = APIRouter(
    prefix="/merchants/{merchant_id}",
    tags=["analytics"],
    dependencies=[Depends(merchant_read_dependency)],
)
reviews_router = APIRouter(
    prefix="/reviews",
    tags=["analytics"],
    dependencies=[Depends(require_permission("MERCHANT", "READ"))],
)


# ---------------------------------------------------------------------------
# Response DTOs
# ---------------------------------------------------------------------------


class TrendBucket(BaseModel):
    period: str
    positive: int
    neutral: int
    negative: int


class NegativeReasonItem(BaseModel):
    reason: str
    count: int


class ReviewItem(BaseModel):
    id: str
    review_text: str
    sentiment: str
    confidence: float
    aspect_labels: list[str]
    negative_reasons: list[str]
    review_date: str | None = None

    model_config = {"from_attributes": True}


class AspectHighlight(BaseModel):
    aspect: str
    positive: int
    neutral: int
    negative: int
    total: int
    positive_rate: float


class ReputationBucket(BaseModel):
    period: str
    positive: int
    neutral: int
    negative: int
    total: int
    positive_rate: float
    change: float | None = None
    trend: str


class ComparisonSummary(BaseModel):
    merchant_id: str
    positive: int
    neutral: int
    negative: int
    total: int
    positive_rate: float
    negative_rate: float


class AspectComparisonRow(BaseModel):
    aspect: str
    merchants: list[dict]


class ReasonComparisonRow(BaseModel):
    reason: str
    merchants: list[dict]


class ComparisonResult(BaseModel):
    merchants: list[str]
    summary: list[ComparisonSummary]
    aspect_comparison: list[AspectComparisonRow]
    negative_reason_comparison: list[ReasonComparisonRow]


class ReplyRequest(BaseModel):
    review_text: str
    sentiment: str
    aspect_labels: list[str] = []
    negative_reasons: list[str] = []
    model_version: str = "unknown"


class ReplyResponse(BaseModel):
    reply_text: str
    template_id: str
    compliance_passed: bool
    model_version: str
    prompt_version: str
    generated_at: str
    evidence_review_ids: list[str] = []
    violations: list[str] = []


class EvidenceItem(BaseModel):
    review_id: str
    review_text: str
    sentiment: str
    aspect_labels: list[str]
    negative_reasons: list[str]
    review_date: str | None = None


class RecommendationItem(BaseModel):
    recommendation_id: str
    category: str
    priority: str
    title: str
    description: str
    related_aspect: str | None = None
    related_negative_reason: str | None = None
    confidence: float
    evidence: list[EvidenceItem] = []


class RecommendationSummary(BaseModel):
    total_reviews: int
    positive: int
    neutral: int
    negative: int
    positive_rate: float
    negative_rate: float
    data_confidence: float


class RecommendationReportDTO(BaseModel):
    merchant_id: str
    model_version: str
    prompt_version: str
    generated_at: str
    evidence_review_ids: list[str]
    summary: RecommendationSummary
    recommendations: list[RecommendationItem]
    low_sample_warning: bool


# ---------------------------------------------------------------------------
# Annotated query-parameter types (B008-safe)
# ---------------------------------------------------------------------------

_GranularityParam = Annotated[str, Query(pattern="^(day|week|month)$")]
_DateParam = Annotated[datetime | None, Query()]
_SentimentParam = Annotated[str | None, Query(pattern="^(POSITIVE|NEUTRAL|NEGATIVE)$")]
_ReasonParam = Annotated[str | None, Query()]
_LimitParam = Annotated[int, Query(ge=1, le=200)]
_OffsetParam = Annotated[int, Query(ge=0)]
_TopNParam = Annotated[int, Query(ge=1, le=20)]
_MinMentionsParam = Annotated[int, Query(ge=1, le=100)]
_MerchantIdsParam = Annotated[list[str], Query(min_length=2, max_length=4)]


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_analytics_service(request: Request, principal: CurrentPrincipal) -> AnalyticsService:
    return AnalyticsService(request.app.state.sentiment_repo.scoped(principal))


AnalyticsServiceDependency = Annotated[AnalyticsService, Depends(get_analytics_service)]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/sentiment-trend")
async def sentiment_trend(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    granularity: _GranularityParam = "day",
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Return sentiment counts grouped by time bucket (day/week/month)."""
    try:
        data = await service.get_sentiment_trend(
            merchant_id,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    return success_response(request, [TrendBucket(**row).model_dump() for row in data])


@router.get("/negative-reasons")
async def negative_reasons(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Return aggregated negative-reason counts."""
    try:
        data = await service.get_negative_reason_aggregation(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    return success_response(request, [NegativeReasonItem(**row).model_dump() for row in data])


@router.get("/reviews")
async def drill_down_reviews(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    sentiment: _SentimentParam = None,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
    negative_reason: _ReasonParam = None,
    limit: _LimitParam = 50,
    offset: _OffsetParam = 0,
) -> dict[str, Any]:
    """Return original reviews matching the given filters."""
    try:
        rows = await service.drill_down_reviews(
            merchant_id,
            sentiment=sentiment,
            start_date=start_date,
            end_date=end_date,
            negative_reason=negative_reason,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc

    items = [
        ReviewItem(
            id=str(row.id),
            review_text=row.review_text,
            sentiment=row.sentiment,
            confidence=row.confidence,
            aspect_labels=_parse_json_field(row.aspect_labels),
            negative_reasons=_parse_json_field(row.negative_reasons),
            review_date=row.review_date.isoformat() if row.review_date else None,
        ).model_dump()
        for row in rows
    ]
    return success_response(request, items)


@router.get("/highlights")
async def merchant_highlights(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    top_n: _TopNParam = 5,
    min_mentions: _MinMentionsParam = 3,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Return the merchant's top differentiated aspect highlights."""
    try:
        data = await service.get_merchant_highlights(
            merchant_id,
            top_n=top_n,
            min_mentions=min_mentions,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    return success_response(request, [AspectHighlight(**row).model_dump() for row in data])


@router.get("/reputation-change")
async def reputation_change(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    granularity: _GranularityParam = "week",
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Return per-period positive rate and trend classification."""
    try:
        data = await service.get_reputation_change(
            merchant_id,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    return success_response(request, [ReputationBucket(**row).model_dump() for row in data])


@compare_router.get("/compare")
async def compare_merchants(
    request: Request,
    service: AnalyticsServiceDependency,
    merchant_ids: _MerchantIdsParam,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Compare 2-4 merchants under the same time window and metrics."""
    try:
        data = await service.compare_merchants(
            merchant_ids,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    result = ComparisonResult(
        merchants=data["merchants"],
        summary=[ComparisonSummary(**s) for s in data["summary"]],
        aspect_comparison=[AspectComparisonRow(**a) for a in data["aspect_comparison"]],
        negative_reason_comparison=[
            ReasonComparisonRow(**r) for r in data["negative_reason_comparison"]
        ],
    )
    return success_response(request, result.model_dump())


# ---------------------------------------------------------------------------
# Reply generation endpoint (TK-402-03)
# ---------------------------------------------------------------------------

_reply_generator = ReplyGenerator()


@reviews_router.post("/{review_id}/reply-suggestions")
async def generate_reply(
    review_id: str,
    request: Request,
    body: ReplyRequest,
) -> dict[str, Any]:
    """Generate a compliant review reply for the given review data."""
    if not body.review_text or not body.review_text.strip():
        raise AppError(400, "INVALID_PARAMETER", "review_text must not be empty")
    valid_sentiments = {"POSITIVE", "NEUTRAL", "NEGATIVE"}
    if body.sentiment not in valid_sentiments:
        raise AppError(
            400,
            "INVALID_PARAMETER",
            f"sentiment must be one of {valid_sentiments}, got {body.sentiment!r}",
        )

    result = _reply_generator.generate(
        review_text=body.review_text,
        sentiment=body.sentiment,
        aspect_labels=body.aspect_labels,
        negative_reasons=body.negative_reasons,
        review_id=review_id,
        model_version=body.model_version,
    )
    response = ReplyResponse(
        reply_text=result.reply_text,
        template_id=result.template_id,
        compliance_passed=result.compliance_passed,
        model_version=result.model_version,
        prompt_version=result.prompt_version,
        generated_at=result.generated_at.isoformat(),
        evidence_review_ids=result.evidence_review_ids,
        violations=result.violations,
    )
    return success_response(request, response.model_dump())


# ---------------------------------------------------------------------------
# Business suggestions endpoint (TK-402-04)
# ---------------------------------------------------------------------------


@business_router.post("/business-suggestions")
async def merchant_recommendations(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    start_date: _DateParam = None,
    end_date: _DateParam = None,
) -> dict[str, Any]:
    """Generate business recommendations with evidence and confidence."""
    try:
        report = await service.generate_recommendations(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc

    dto = RecommendationReportDTO(
        merchant_id=report.merchant_id,
        model_version=report.model_version,
        prompt_version=report.prompt_version,
        generated_at=report.generated_at.isoformat(),
        evidence_review_ids=report.evidence_review_ids,
        summary=RecommendationSummary(
            total_reviews=report.summary["total_reviews"],
            positive=report.summary["positive"],
            neutral=report.summary["neutral"],
            negative=report.summary["negative"],
            positive_rate=report.summary["positive_rate"],
            negative_rate=report.summary["negative_rate"],
            data_confidence=report.summary["data_confidence"],
        ),
        recommendations=[
            RecommendationItem(
                recommendation_id=rec.recommendation_id,
                category=rec.category,
                priority=rec.priority,
                title=rec.title,
                description=rec.description,
                related_aspect=rec.related_aspect,
                related_negative_reason=rec.related_negative_reason,
                confidence=rec.confidence,
                evidence=[
                    EvidenceItem(
                        review_id=ev.review_id,
                        review_text=ev.review_text,
                        sentiment=ev.sentiment,
                        aspect_labels=ev.aspect_labels,
                        negative_reasons=ev.negative_reasons,
                        review_date=ev.review_date,
                    )
                    for ev in rec.evidence
                ],
            )
            for rec in report.recommendations
        ],
        low_sample_warning=report.low_sample_warning,
    )
    return success_response(request, dto.model_dump())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_json_field(value: str | list) -> list:
    """Safely parse a JSON column that may already be a Python list."""
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
