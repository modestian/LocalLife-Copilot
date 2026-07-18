"""Sentiment analytics REST endpoints."""

import json
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from app.application.analytics import AnalyticsService
from app.core.api import success_response
from app.core.errors import AppError

router = APIRouter(prefix="/merchants/{merchant_id}/analytics", tags=["analytics"])


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


# ---------------------------------------------------------------------------
# Annotated query-parameter types (B008-safe)
# ---------------------------------------------------------------------------

_GranularityParam = Annotated[str, Query(pattern="^(day|week|month)$")]
_DateParam = Annotated[datetime | None, Query()]
_SentimentParam = Annotated[str | None, Query(pattern="^(POSITIVE|NEUTRAL|NEGATIVE)$")]
_ReasonParam = Annotated[str | None, Query()]
_LimitParam = Annotated[int, Query(ge=1, le=200)]
_OffsetParam = Annotated[int, Query(ge=0)]


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_analytics_service(request: Request) -> AnalyticsService:
    return request.app.state.analytics_service


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
