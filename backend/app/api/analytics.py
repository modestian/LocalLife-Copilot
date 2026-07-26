"""Sentiment analytics REST endpoints."""

import json
from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.api.dependencies.authorization import (
    CurrentPrincipal,
    require_permission,
    require_resource_access,
)
from app.application.analytics import AnalyticsService
from app.application.authorization import ResourceType
from app.application.content_safety import ContentDirection
from app.application.reply_generator import ReplyGenerator
from app.core.api import get_request_id, success_response
from app.core.errors import AppError

merchant_read_dependency = require_resource_access(
    ResourceType.MERCHANT,
    "READ",
    path_parameter="merchant_id",
)
merchant_compare_dependency = require_permission("MERCHANT", "READ")

router = APIRouter(
    prefix="/merchants/{merchant_id}/analytics",
    tags=["analytics"],
    dependencies=[Depends(merchant_read_dependency)],
)
compare_router = APIRouter(
    prefix="/merchants",
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


class ComparisonRequest(BaseModel):
    merchant_ids: list[str] = Field(min_length=2, max_length=4)
    start_date: datetime | None = None
    end_date: datetime | None = None


class ComparisonMerchantMetric(BaseModel):
    merchant_id: str
    merchant_name: str
    sample_count: int
    positive_rate: float
    aspect_counts: dict[str, int]
    negative_reason_counts: dict[str, int]


class ComparisonResult(BaseModel):
    period_start: str
    period_end: str
    metric_definition: str
    minimum_sample_size: int
    insufficient_data: bool
    merchants: list[ComparisonMerchantMetric]


class ReplySuggestionRequest(BaseModel):
    tone: str = "EMPATHETIC"
    aspect_labels: list[str] = []
    prohibited_commitments: list[str] = []


class ReplySuggestionResponse(BaseModel):
    draft: str
    model_version: str
    prompt_version: str
    generated_at: str
    evidence_review_ids: list[str] = []


class EvidenceReview(BaseModel):
    review_id: str
    review_text: str
    sentiment: str | None = None
    reviewed_at: str | None = None


class BusinessSuggestionItem(BaseModel):
    id: str
    title: str
    content: str
    confidence: float
    period_start: str
    period_end: str
    evidence_review_ids: list[str] = []
    evidence_reviews: list[EvidenceReview] = []


class BusinessSuggestionRequest(BaseModel):
    focus_aspects: list[str] = []
    start_date: datetime | None = None
    end_date: datetime | None = None


class BusinessSuggestionResult(BaseModel):
    suggestions: list[BusinessSuggestionItem]
    insufficient_data: bool
    evidence_conflict: bool = False
    model_version: str
    prompt_version: str
    generated_at: str


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


@compare_router.post("/compare")
async def compare_merchants(
    request: Request,
    service: AnalyticsServiceDependency,
    body: ComparisonRequest,
) -> dict[str, Any]:
    """Compare 2-4 merchants under the same time window and metrics."""
    try:
        data = await service.compare_merchants(
            body.merchant_ids,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc
    result = ComparisonResult(
        period_start=data["period_start"],
        period_end=data["period_end"],
        metric_definition=data["metric_definition"],
        minimum_sample_size=data["minimum_sample_size"],
        insufficient_data=data["insufficient_data"],
        merchants=[ComparisonMerchantMetric(**m) for m in data["merchants"]],
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
    service: AnalyticsServiceDependency,
    body: ReplySuggestionRequest,
) -> dict[str, Any]:
    """Generate a compliant review reply for the given review data."""
    valid_tones = {"EMPATHETIC", "PROFESSIONAL", "CONCISE"}
    if body.tone not in valid_tones:
        raise AppError(
            400,
            "INVALID_PARAMETER",
            f"tone must be one of {valid_tones}, got {body.tone!r}",
        )

    try:
        review_uuid = UUID(review_id)
    except ValueError as exc:
        raise AppError(422, "VALIDATION_ERROR", "review_id 格式无效") from exc

    review = await service.find_review_by_id(review_uuid)
    if review is None:
        raise AppError(404, "NOT_FOUND", "点评不存在或无访问权限")

    aspect_labels = (
        body.aspect_labels if body.aspect_labels else _parse_json_field(review.aspect_labels)
    )
    negative_reasons = _parse_json_field(review.negative_reasons)

    result = _reply_generator.generate(
        review_text=review.review_text,
        sentiment=review.sentiment,
        aspect_labels=aspect_labels,
        negative_reasons=negative_reasons,
        review_id=review_id,
        model_version=getattr(review, "model_version", "unknown"),
        tone=body.tone,
        prohibited_commitments=body.prohibited_commitments,
    )
    response = ReplySuggestionResponse(
        draft=result.reply_text,
        model_version=result.model_version,
        prompt_version=result.prompt_version,
        generated_at=result.generated_at.isoformat(),
        evidence_review_ids=result.evidence_review_ids,
    )
    return success_response(request, response.model_dump())


# ---------------------------------------------------------------------------
# Reply submission & retrieval endpoints
# ---------------------------------------------------------------------------


class ReplyCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    tone: str = "EMPATHETIC"
    source: str = "MANUAL"


class MerchantReplyResponse(BaseModel):
    id: str
    review_id: str
    merchant_id: str
    content: str
    tone: str
    source: str
    created_at: str
    updated_at: str


def _ops_repository(request: Request):
    repository = getattr(request.app.state, "operations_repository", None)
    if repository is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "运营数据服务尚未配置")
    return repository


@reviews_router.post("/{review_id}/replies", status_code=201)
async def submit_reply(
    review_id: str,
    request: Request,
    body: ReplyCreateRequest,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Submit a merchant reply for a review."""
    valid_tones = {"EMPATHETIC", "PROFESSIONAL", "CONCISE"}
    if body.tone not in valid_tones:
        raise AppError(
            400,
            "INVALID_PARAMETER",
            f"tone must be one of {valid_tones}, got {body.tone!r}",
        )
    valid_sources = {"SUGGESTION", "MANUAL"}
    if body.source not in valid_sources:
        raise AppError(
            400,
            "INVALID_PARAMETER",
            f"source must be one of {valid_sources}, got {body.source!r}",
        )

    try:
        review_uuid = UUID(review_id)
    except ValueError as exc:
        raise AppError(422, "VALIDATION_ERROR", "review_id 格式无效") from exc

    repo = _ops_repository(request)
    review = await repo.get_review(review_uuid)
    if review is None:
        raise AppError(404, "NOT_FOUND", "点评不存在")

    merchant_id = await repo.resolve_merchant_id(review_uuid) or str(review_uuid)

    # Same sensitive-word rules as user reviews: matched replies are auto-rejected
    reply_status = "PENDING"
    safety_service = getattr(request.app.state, "content_safety_service", None)
    if safety_service is not None:
        check_result = await safety_service.check(
            content=body.content,
            direction=ContentDirection.INPUT,
            actor_id=principal.user_id,
            request_id=get_request_id(request),
        )
        if not check_result.allowed:
            reply_status = "REJECTED"

    reply = await repo.create_reply(
        review_id=review_uuid,
        merchant_id=merchant_id,
        content=body.content,
        tone=body.tone,
        source=body.source,
        created_by=principal.user_id,
        status=reply_status,
    )

    return success_response(
        request,
        {
            "id": str(reply.id),
            "review_id": str(reply.review_id),
            "merchant_id": str(reply.merchant_id),
            "content": reply.content,
            "tone": reply.tone,
            "source": reply.source,
            "status": reply.status,
            "created_at": reply.created_at.isoformat(),
            "updated_at": reply.updated_at.isoformat(),
        },
        message=(
            "回复包含违禁内容，已自动审核不通过"
            if reply.status == "REJECTED"
            else "回复已提交，等待审核"
        ),
    )


@reviews_router.get("/{review_id}/replies")
async def list_replies(
    review_id: str,
    request: Request,
) -> dict[str, Any]:
    """List all merchant replies for a given review."""
    try:
        review_uuid = UUID(review_id)
    except ValueError as exc:
        raise AppError(422, "VALIDATION_ERROR", "review_id 格式无效") from exc

    repo = _ops_repository(request)
    replies = await repo.get_replies_for_review(review_uuid)

    return success_response(
        request,
        {
            "items": [
                {
                    "id": str(reply.id),
                    "review_id": str(reply.review_id),
                    "merchant_id": str(reply.merchant_id),
                    "content": reply.content,
                    "tone": reply.tone,
                    "source": reply.source,
                    "status": reply.status,
                    "created_at": reply.created_at.isoformat(),
                    "updated_at": reply.updated_at.isoformat(),
                }
                for reply in replies
            ],
            "total": len(replies),
        },
    )


# ---------------------------------------------------------------------------
# Business suggestions endpoint (TK-402-04)
# ---------------------------------------------------------------------------


@business_router.post("/business-suggestions")
async def merchant_recommendations(
    merchant_id: str,
    request: Request,
    service: AnalyticsServiceDependency,
    body: BusinessSuggestionRequest,
) -> dict[str, Any]:
    """Generate business recommendations with evidence and confidence."""
    try:
        report = await service.generate_recommendations(
            merchant_id,
            focus_aspects=body.focus_aspects or None,
            start_date=body.start_date,
            end_date=body.end_date,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_PARAMETER", str(exc)) from exc

    period_start = body.start_date.isoformat() if body.start_date else ""
    period_end = body.end_date.isoformat() if body.end_date else ""

    dto = BusinessSuggestionResult(
        suggestions=[
            BusinessSuggestionItem(
                id=rec.recommendation_id,
                title=rec.title,
                content=rec.description,
                confidence=rec.confidence,
                period_start=period_start,
                period_end=period_end,
                evidence_review_ids=[ev.review_id for ev in rec.evidence],
                evidence_reviews=[
                    EvidenceReview(
                        review_id=ev.review_id,
                        review_text=ev.review_text,
                        sentiment=ev.sentiment,
                        reviewed_at=ev.review_date,
                    )
                    for ev in rec.evidence
                ],
            )
            for rec in report.recommendations
        ],
        insufficient_data=report.low_sample_warning,
        evidence_conflict=False,
        model_version=report.model_version,
        prompt_version=report.prompt_version,
        generated_at=report.generated_at.isoformat(),
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
