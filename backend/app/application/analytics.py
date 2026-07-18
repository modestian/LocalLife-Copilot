"""Sentiment analytics application service.

Provides use-case methods for querying sentiment trends, negative-reason
aggregation and review drill-down.  Delegates to the repository layer and
performs parameter validation only – no business-rule mutation.
"""

from datetime import datetime
from typing import Literal, Protocol

from app.application.recommendation_generator import (
    RecommendationGenerator,
    RecommendationReport,
)
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

    async def get_comparison_stats(
        self,
        merchant_ids: list[str],
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, dict]: ...

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

    async def compare_merchants(
        self,
        merchant_ids: list[str],
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict:
        """Compare 2-4 merchants under the same time window and metrics.

        Returns a dict with three sections:
        - ``summary``: per-merchant sentiment distribution
        - ``aspect_comparison``: per-aspect cross-merchant comparison
        - ``negative_reason_comparison``: per-reason cross-merchant comparison
        """
        _validate_merchant_ids(merchant_ids)
        _validate_date_range(start_date, end_date)

        # 1. Summary stats (single SQL pass)
        summary = await self._repository.get_comparison_stats(
            merchant_ids,
            start_date=start_date,
            end_date=end_date,
        )

        # 2. Aspect comparison (per-merchant, then align)
        aspect_maps: dict[str, list[dict]] = {}
        for mid in merchant_ids:
            aspect_maps[mid] = await self._repository.get_aspect_sentiment_stats(
                mid,
                start_date=start_date,
                end_date=end_date,
            )

        # Collect all aspects across merchants
        all_aspects: set[str] = set()
        for stats in aspect_maps.values():
            all_aspects.update(s["aspect"] for s in stats)

        aspect_comparison: list[dict] = []
        for aspect in sorted(all_aspects):
            merchants: list[dict] = []
            for mid in merchant_ids:
                found = next((s for s in aspect_maps[mid] if s["aspect"] == aspect), None)
                if found:
                    merchants.append(
                        {
                            "merchant_id": mid,
                            "positive_rate": found["positive_rate"],
                            "total": found["total"],
                        }
                    )
                else:
                    merchants.append({"merchant_id": mid, "positive_rate": 0.0, "total": 0})
            aspect_comparison.append({"aspect": aspect, "merchants": merchants})

        # 3. Negative reason comparison (per-merchant, then align)
        reason_maps: dict[str, list[dict]] = {}
        for mid in merchant_ids:
            reason_maps[mid] = await self._repository.get_negative_reason_aggregation(
                mid,
                start_date=start_date,
                end_date=end_date,
            )

        all_reasons: set[str] = set()
        for reasons in reason_maps.values():
            all_reasons.update(r["reason"] for r in reasons)

        reason_comparison: list[dict] = []
        for reason in sorted(all_reasons):
            merchants = []
            for mid in merchant_ids:
                found = next((r for r in reason_maps[mid] if r["reason"] == reason), None)
                merchants.append({"merchant_id": mid, "count": found["count"] if found else 0})
            reason_comparison.append({"reason": reason, "merchants": merchants})

        return {
            "merchants": merchant_ids,
            "summary": [summary[mid] for mid in merchant_ids],
            "aspect_comparison": aspect_comparison,
            "negative_reason_comparison": reason_comparison,
        }

    async def generate_recommendations(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> RecommendationReport:
        """Generate business recommendations with evidence and confidence.

        Orchestrates data fetching from the repository, then delegates to
        :class:`RecommendationGenerator` for rule-based recommendation synthesis.
        """
        _validate_merchant_id(merchant_id)
        _validate_date_range(start_date, end_date)

        # 1. Summary stats (reuse comparison endpoint's query)
        comparison = await self._repository.get_comparison_stats(
            [merchant_id],
            start_date=start_date,
            end_date=end_date,
        )
        summary_stats = comparison.get(
            merchant_id,
            {
                "positive": 0,
                "neutral": 0,
                "negative": 0,
                "total": 0,
            },
        )

        # 2. Negative reason aggregation
        negative_reason_stats = await self._repository.get_negative_reason_aggregation(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )

        # 3. Aspect sentiment stats
        aspect_stats = await self._repository.get_aspect_sentiment_stats(
            merchant_id,
            start_date=start_date,
            end_date=end_date,
        )

        # 4. Fetch evidence reviews for each negative reason
        evidence_reviews: dict[str, list[ReviewAnalysis]] = {}
        for stat in negative_reason_stats:
            reason = stat["reason"]
            count = stat["count"]
            if count < 2:
                continue
            reviews = await self._repository.drill_down_reviews(
                merchant_id,
                sentiment="NEGATIVE",
                start_date=start_date,
                end_date=end_date,
                negative_reason=reason,
                limit=5,
            )
            evidence_reviews[reason] = reviews

        # 5. Extract model_version from evidence reviews (for traceability)
        model_version = "unknown"
        for reviews in evidence_reviews.values():
            if reviews:
                model_version = getattr(reviews[0], "model_version", "unknown")
                break

        # 6. Generate report
        generator = RecommendationGenerator()
        return generator.generate(
            merchant_id=merchant_id,
            negative_reason_stats=negative_reason_stats,
            aspect_stats=aspect_stats,
            summary_stats=summary_stats,
            evidence_reviews=evidence_reviews,
            model_version=model_version,
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


def _validate_merchant_ids(merchant_ids: list[str]) -> None:
    """Validate merchant list for comparison: 2-4 unique non-empty IDs."""
    if not isinstance(merchant_ids, list):
        raise ValueError("merchant_ids must be a list")
    if len(merchant_ids) < 2:
        raise ValueError("at least 2 merchants are required for comparison")
    if len(merchant_ids) > 4:
        raise ValueError("at most 4 merchants can be compared at once")
    for mid in merchant_ids:
        if not mid or not mid.strip():
            raise ValueError("merchant_id must not be empty")
    if len(set(merchant_ids)) != len(merchant_ids):
        raise ValueError("merchant_ids must not contain duplicates")
