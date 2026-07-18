"""Sentiment analytics application service.

Provides use-case methods for querying sentiment trends, negative-reason
aggregation and review drill-down.  Delegates to the repository layer and
performs parameter validation only – no business-rule mutation.
"""

from datetime import datetime
from typing import Literal, Protocol

from app.infrastructure.db.models.sentiment import ReviewAnalysis


class AnalyticsRepository(Protocol):
    """Port that the infrastructure repository must satisfy."""

    async def get_sentiment_trend(
        self,
        merchant_id: str,
        *,
        granularity: Literal["day", "week", "month"] = "day",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]: ...

    async def get_negative_reason_aggregation(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]: ...

    async def get_aspect_sentiment_stats(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]: ...

    async def get_reputation_change(
        self,
        merchant_id: str,
        *,
        granularity: Literal["day", "week", "month"] = "week",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]: ...

    async def drill_down_reviews(
        self,
        merchant_id: str,
        *,
        sentiment: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        negative_reason: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReviewAnalysis]: ...


_VALID_GRANULARITIES = {"day", "week", "month"}
_VALID_SENTIMENTS = {"POSITIVE", "NEUTRAL", "NEGATIVE"}


class AnalyticsService:
    """Orchestrates analytics queries with parameter validation."""

    def __init__(self, repository: AnalyticsRepository) -> None:
        self._repository = repository

    async def get_sentiment_trend(
        self,
        merchant_id: str,
        *,
        granularity: str = "day",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return sentiment counts grouped by time bucket."""
        _validate_merchant_id(merchant_id)
        if granularity not in _VALID_GRANULARITIES:
            raise ValueError(
                f"granularity must be one of {_VALID_GRANULARITIES}, got {granularity!r}"
            )
        _validate_date_range(start_date, end_date)

        return await self._repository.get_sentiment_trend(
            merchant_id,
            granularity=granularity,  # type: ignore[arg-type]
            start_date=start_date,
            end_date=end_date,
        )

    async def get_negative_reason_aggregation(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return aggregated negative-reason counts."""
        _validate_merchant_id(merchant_id)
        _validate_date_range(start_date, end_date)

        return await self._repository.get_negative_reason_aggregation(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )

    async def drill_down_reviews(
        self,
        merchant_id: str,
        *,
        sentiment: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        negative_reason: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReviewAnalysis]:
        """Return original reviews matching the given filters."""
        _validate_merchant_id(merchant_id)
        if sentiment is not None and sentiment not in _VALID_SENTIMENTS:
            raise ValueError(f"sentiment must be one of {_VALID_SENTIMENTS}, got {sentiment!r}")
        _validate_date_range(start_date, end_date)
        limit = _validate_limit(limit)
        offset = _validate_offset(offset)

        return await self._repository.drill_down_reviews(
            merchant_id,
            sentiment=sentiment,
            start_date=start_date,
            end_date=end_date,
            negative_reason=negative_reason,
            limit=limit,
            offset=offset,
        )

    async def get_merchant_highlights(
        self,
        merchant_id: str,
        *,
        top_n: int = 5,
        min_mentions: int = 3,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return the merchant's top differentiated aspects.

        Filters aspects with at least ``min_mentions`` total reviews,
        then returns the top ``top_n`` by ``positive_rate``.
        """
        _validate_merchant_id(merchant_id)
        _validate_date_range(start_date, end_date)
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        if min_mentions < 1:
            raise ValueError("min_mentions must be at least 1")

        stats = await self._repository.get_aspect_sentiment_stats(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )
        highlights = [s for s in stats if s["total"] >= min_mentions]
        return highlights[:top_n]

    async def get_reputation_change(
        self,
        merchant_id: str,
        *,
        granularity: str = "week",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return per-period positive rate and trend classification."""
        _validate_merchant_id(merchant_id)
        if granularity not in _VALID_GRANULARITIES:
            raise ValueError(
                f"granularity must be one of {_VALID_GRANULARITIES}, got {granularity!r}"
            )
        _validate_date_range(start_date, end_date)

        return await self._repository.get_reputation_change(
            merchant_id,
            granularity=granularity,  # type: ignore[arg-type]
            start_date=start_date,
            end_date=end_date,
        )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_merchant_id(value: str) -> None:
    if not value or not value.strip():
        raise ValueError("merchant_id must not be empty")


def _validate_date_range(start_date: datetime | None, end_date: datetime | None) -> None:
    if start_date and end_date and start_date >= end_date:
        raise ValueError("start_date must be earlier than end_date")


def _validate_limit(value: int) -> int:
    if not 1 <= value <= 200:
        raise ValueError("limit must be between 1 and 200")
    return value


def _validate_offset(value: int) -> int:
    if value < 0:
        raise ValueError("offset must be non-negative")
    return value
