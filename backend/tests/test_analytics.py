"""Unit tests for analytics application service and API endpoints."""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.application.analytics import AnalyticsService
from app.core.ids import uuid7

# ---------------------------------------------------------------------------
# In-memory fake repository
# ---------------------------------------------------------------------------


@dataclass
class FakeReviewAnalysis:
    """Lightweight stand-in for the ORM model."""

    id: UUID
    merchant_id: str
    review_text: str
    sentiment: str
    confidence: float
    aspect_labels: str
    negative_reasons: str
    review_date: datetime | None = None


class InMemoryAnalyticsRepository:
    """Fake repository that stores data in memory and mimics aggregation."""

    def __init__(self, records: list[FakeReviewAnalysis] | None = None) -> None:
        self._records = records or []

    async def get_sentiment_trend(
        self,
        merchant_id: str,
        *,
        granularity: Literal["day", "week", "month"] = "day",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        fmt_map = {"day": "%Y-%m-%d", "week": "%x-W%v", "month": "%Y-%m"}
        fmt = fmt_map.get(granularity, "%Y-%m-%d")

        filtered = [
            r
            for r in self._records
            if r.merchant_id == merchant_id
            and r.review_date is not None
            and (start_date is None or r.review_date >= start_date)
            and (end_date is None or r.review_date < end_date)
        ]

        buckets: dict[str, Counter[str]] = {}
        for r in filtered:
            period = r.review_date.strftime(fmt)
            if period not in buckets:
                buckets[period] = Counter()
            buckets[period][r.sentiment] += 1

        return [
            {
                "period": period,
                "positive": counts.get("POSITIVE", 0),
                "neutral": counts.get("NEUTRAL", 0),
                "negative": counts.get("NEGATIVE", 0),
            }
            for period, counts in sorted(buckets.items())
        ]

    async def get_negative_reason_aggregation(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        filtered = [
            r
            for r in self._records
            if r.merchant_id == merchant_id
            and r.sentiment == "NEGATIVE"
            and (start_date is None or (r.review_date and r.review_date >= start_date))
            and (end_date is None or (r.review_date and r.review_date < end_date))
        ]

        counter: Counter[str] = Counter()
        for r in filtered:
            try:
                reasons = json.loads(r.negative_reasons)
                if isinstance(reasons, list):
                    counter.update(reasons)
            except (json.JSONDecodeError, TypeError):
                continue

        return [{"reason": reason, "count": count} for reason, count in counter.most_common()]

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
    ) -> list[FakeReviewAnalysis]:
        filtered = [
            r
            for r in self._records
            if r.merchant_id == merchant_id
            and (sentiment is None or r.sentiment == sentiment)
            and (start_date is None or (r.review_date and r.review_date >= start_date))
            and (end_date is None or (r.review_date and r.review_date < end_date))
        ]

        if negative_reason:
            result = []
            for r in filtered:
                try:
                    reasons = json.loads(r.negative_reasons)
                    if isinstance(reasons, list) and negative_reason in reasons:
                        result.append(r)
                except (json.JSONDecodeError, TypeError):
                    continue
                if len(result) >= limit:
                    break
            return result

        return filtered[offset : offset + limit]

    async def get_aspect_sentiment_stats(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        filtered = [
            r
            for r in self._records
            if r.merchant_id == merchant_id
            and (start_date is None or (r.review_date and r.review_date >= start_date))
            and (end_date is None or (r.review_date and r.review_date < end_date))
        ]

        stats: dict[str, Counter[str]] = {}
        for r in filtered:
            try:
                aspects = json.loads(r.aspect_labels)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(aspects, list):
                continue
            for aspect in aspects:
                if aspect not in stats:
                    stats[aspect] = Counter()
                stats[aspect][r.sentiment] += 1

        result: list[dict] = []
        for aspect, counts in stats.items():
            positive = counts.get("POSITIVE", 0)
            neutral = counts.get("NEUTRAL", 0)
            negative = counts.get("NEGATIVE", 0)
            total = positive + neutral + negative
            result.append(
                {
                    "aspect": aspect,
                    "positive": positive,
                    "neutral": neutral,
                    "negative": negative,
                    "total": total,
                    "positive_rate": round(positive / total, 4) if total else 0.0,
                }
            )
        result.sort(key=lambda x: x["positive_rate"], reverse=True)
        return result

    async def get_reputation_change(
        self,
        merchant_id: str,
        *,
        granularity: Literal["day", "week", "month"] = "week",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        trend_data = await self.get_sentiment_trend(
            merchant_id,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        )
        result: list[dict] = []
        prev_rate: float | None = None
        threshold = 0.05
        for bucket in trend_data:
            total = bucket["positive"] + bucket["neutral"] + bucket["negative"]
            rate = round(bucket["positive"] / total, 4) if total else 0.0
            if prev_rate is None:
                change = None
                trend = "stable"
            else:
                change = round(rate - prev_rate, 4)
                if change > threshold:
                    trend = "improving"
                elif change < -threshold:
                    trend = "declining"
                else:
                    trend = "stable"
            result.append(
                {
                    "period": bucket["period"],
                    "positive": bucket["positive"],
                    "neutral": bucket["neutral"],
                    "negative": bucket["negative"],
                    "total": total,
                    "positive_rate": rate,
                    "change": change,
                    "trend": trend,
                }
            )
            prev_rate = rate
        return result

    async def get_comparison_stats(
        self,
        merchant_ids: list[str],
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, dict]:
        filtered = [
            r
            for r in self._records
            if r.merchant_id in merchant_ids
            and (start_date is None or (r.review_date and r.review_date >= start_date))
            and (end_date is None or (r.review_date and r.review_date < end_date))
        ]

        stats: dict[str, dict] = {}
        for mid in merchant_ids:
            mid_records = [r for r in filtered if r.merchant_id == mid]
            positive = sum(1 for r in mid_records if r.sentiment == "POSITIVE")
            neutral = sum(1 for r in mid_records if r.sentiment == "NEUTRAL")
            negative = sum(1 for r in mid_records if r.sentiment == "NEGATIVE")
            total = positive + neutral + negative
            stats[mid] = {
                "merchant_id": mid,
                "positive": positive,
                "neutral": neutral,
                "negative": negative,
                "total": total,
                "positive_rate": round(positive / total, 4) if total else 0.0,
                "negative_rate": round(negative / total, 4) if total else 0.0,
            }
        return stats


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_records() -> list[FakeReviewAnalysis]:
    """Create sample review records for testing."""
    base_date = datetime(2025, 7, 1, 12, 0, 0)
    return [
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M001",
            review_text="味道很好，服务周到",
            sentiment="POSITIVE",
            confidence=0.95,
            aspect_labels=json.dumps(["taste", "service"]),
            negative_reasons="[]",
            review_date=base_date,
        ),
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M001",
            review_text="环境一般，价格偏贵",
            sentiment="NEUTRAL",
            confidence=0.70,
            aspect_labels=json.dumps(["environment", "price"]),
            negative_reasons="[]",
            review_date=base_date,
        ),
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M001",
            review_text="等太久了，服务员态度差",
            sentiment="NEGATIVE",
            confidence=0.88,
            aspect_labels=json.dumps(["service"]),
            negative_reasons=json.dumps(["slow_wait", "rude_staff"]),
            review_date=base_date,
        ),
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M001",
            review_text="菜凉了，上菜太慢",
            sentiment="NEGATIVE",
            confidence=0.85,
            aspect_labels=json.dumps(["taste", "service"]),
            negative_reasons=json.dumps(["slow_wait", "cold_food"]),
            review_date=datetime(2025, 7, 2, 12, 0, 0),
        ),
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M002",
            review_text="非常好吃",
            sentiment="POSITIVE",
            confidence=0.99,
            aspect_labels=json.dumps(["taste"]),
            negative_reasons="[]",
            review_date=base_date,
        ),
    ]


@pytest.fixture
def service(sample_records: list[FakeReviewAnalysis]) -> AnalyticsService:
    repo = InMemoryAnalyticsRepository(sample_records)
    return AnalyticsService(repo)


# ---------------------------------------------------------------------------
# Application Service tests
# ---------------------------------------------------------------------------


class TestAnalyticsServiceValidation:
    def test_empty_merchant_id_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="merchant_id must not be empty"):
            import asyncio

            asyncio.run(service.get_sentiment_trend(""))

    def test_invalid_granularity_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="granularity must be one of"):
            import asyncio

            asyncio.run(service.get_sentiment_trend("M001", granularity="year"))

    def test_invalid_date_range_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="start_date must be earlier"):
            import asyncio

            asyncio.run(
                service.get_sentiment_trend(
                    "M001",
                    start_date=datetime(2025, 7, 10),
                    end_date=datetime(2025, 7, 1),
                )
            )

    def test_invalid_sentiment_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="sentiment must be one of"):
            import asyncio

            asyncio.run(service.drill_down_reviews("M001", sentiment="UNKNOWN"))

    def test_invalid_limit_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="limit must be between"):
            import asyncio

            asyncio.run(service.drill_down_reviews("M001", limit=500))

    def test_invalid_offset_raises(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="offset must be non-negative"):
            import asyncio

            asyncio.run(service.drill_down_reviews("M001", offset=-1))


class TestSentimentTrend:
    @pytest.mark.asyncio
    async def test_trend_by_day(self, service: AnalyticsService) -> None:
        result = await service.get_sentiment_trend("M001", granularity="day")
        assert len(result) >= 1
        day1 = next(r for r in result if r["period"] == "2025-07-01")
        assert day1["positive"] == 1
        assert day1["neutral"] == 1
        assert day1["negative"] == 1

    @pytest.mark.asyncio
    async def test_trend_filters_by_merchant(self, service: AnalyticsService) -> None:
        result = await service.get_sentiment_trend("M002", granularity="day")
        assert len(result) == 1
        assert result[0]["positive"] == 1
        assert result[0]["negative"] == 0

    @pytest.mark.asyncio
    async def test_trend_with_date_range(self, service: AnalyticsService) -> None:
        result = await service.get_sentiment_trend(
            "M001",
            granularity="day",
            start_date=datetime(2025, 7, 2),
            end_date=datetime(2025, 7, 3),
        )
        assert len(result) == 1
        assert result[0]["negative"] == 1


class TestNegativeReasonAggregation:
    @pytest.mark.asyncio
    async def test_aggregation_counts(self, service: AnalyticsService) -> None:
        result = await service.get_negative_reason_aggregation("M001")
        reasons_dict = {item["reason"]: item["count"] for item in result}
        assert reasons_dict.get("slow_wait") == 2
        assert reasons_dict.get("rude_staff") == 1
        assert reasons_dict.get("cold_food") == 1

    @pytest.mark.asyncio
    async def test_aggregation_sorted_by_count(self, service: AnalyticsService) -> None:
        result = await service.get_negative_reason_aggregation("M001")
        counts = [item["count"] for item in result]
        assert counts == sorted(counts, reverse=True)

    @pytest.mark.asyncio
    async def test_aggregation_empty_for_positive_merchant(
        self, sample_records: list[FakeReviewAnalysis]
    ) -> None:
        # Create repo with only positive reviews
        positive_only = [r for r in sample_records if r.sentiment == "POSITIVE"]
        repo = InMemoryAnalyticsRepository(positive_only)
        service = AnalyticsService(repo)
        result = await service.get_negative_reason_aggregation("M001")
        assert result == []


class TestDrillDownReviews:
    @pytest.mark.asyncio
    async def test_drill_down_all(self, service: AnalyticsService) -> None:
        result = await service.drill_down_reviews("M001")
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_drill_down_by_sentiment(self, service: AnalyticsService) -> None:
        result = await service.drill_down_reviews("M001", sentiment="NEGATIVE")
        assert len(result) == 2
        assert all(r.sentiment == "NEGATIVE" for r in result)

    @pytest.mark.asyncio
    async def test_drill_down_by_negative_reason(self, service: AnalyticsService) -> None:
        result = await service.drill_down_reviews("M001", negative_reason="slow_wait")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_drill_down_pagination(self, service: AnalyticsService) -> None:
        result = await service.drill_down_reviews("M001", limit=2, offset=0)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _create_test_client(sample_records: list[FakeReviewAnalysis]) -> TestClient:
    """Create a minimal FastAPI TestClient with mocked analytics service.

    Builds a standalone app without importing app.main (which pulls in
    opensearchpy, redis, etc.) — only the analytics router is mounted.
    """
    from fastapi import FastAPI

    from app.api.analytics import business_router as analytics_business_router
    from app.api.analytics import compare_router as analytics_compare_router
    from app.api.analytics import get_analytics_service
    from app.api.analytics import router as analytics_router
    from app.api.dependencies.authorization import get_current_principal
    from app.application.authorization import AuthorizationPrincipal, RoleInfo
    from app.core.api import install_api_contract
    from app.core.config import get_settings

    app = FastAPI()
    settings = get_settings()
    app.state.settings = settings
    install_api_contract(app, settings)
    app.include_router(analytics_router, prefix=settings.api_v1_prefix)
    app.include_router(analytics_compare_router, prefix=settings.api_v1_prefix)
    app.include_router(analytics_business_router, prefix=settings.api_v1_prefix)

    repo = InMemoryAnalyticsRepository(sample_records)
    service = AnalyticsService(repo)
    app.dependency_overrides[get_analytics_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: AuthorizationPrincipal(
        user_id=uuid7(),
        username="analytics-test-admin",
        display_name="Analytics test admin",
        email=None,
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "Platform admin"),),
        permissions=(),
        resource_grants=(),
    )

    return TestClient(app)


class TestSentimentTrendEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/sentiment-trend")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        assert isinstance(body["data"], list)
        assert all(
            {"period", "positive", "neutral", "negative"} <= set(item.keys())
            for item in body["data"]
        )

    def test_with_granularity(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/sentiment-trend?granularity=month")
        assert response.status_code == 200

    def test_invalid_granularity(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/sentiment-trend?granularity=year")
        assert response.status_code == 422  # Validation error from FastAPI


class TestNegativeReasonsEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/negative-reasons")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        assert isinstance(body["data"], list)
        if body["data"]:
            assert {"reason", "count"} <= set(body["data"][0].keys())


class TestDrillDownReviewsEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reviews")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        assert isinstance(body["data"], list)

    def test_with_filters(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get(
            "/api/v1/merchants/M001/analytics/reviews?sentiment=NEGATIVE&negative_reason=slow_wait"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2

    def test_invalid_sentiment(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reviews?sentiment=INVALID")
        assert response.status_code == 422

    def test_review_item_structure(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reviews?limit=1")
        assert response.status_code == 200
        body = response.json()
        if body["data"]:
            item = body["data"][0]
            assert "id" in item
            assert "review_text" in item
            assert "sentiment" in item
            assert "confidence" in item
            assert isinstance(item["aspect_labels"], list)
            assert isinstance(item["negative_reasons"], list)


# ---------------------------------------------------------------------------
# Merchant highlights tests (TK-402-01)
# ---------------------------------------------------------------------------


class TestMerchantHighlights:
    @pytest.mark.asyncio
    async def test_highlights_returns_top_aspects(self, service: AnalyticsService) -> None:
        # min_mentions=2 so taste (total=2) is included
        result = await service.get_merchant_highlights("M001", min_mentions=2)
        assert len(result) >= 1
        aspects = {item["aspect"] for item in result}
        assert "taste" in aspects
        assert "service" in aspects
        # Sorted by positive_rate descending
        rates = [item["positive_rate"] for item in result]
        assert rates == sorted(rates, reverse=True)

    @pytest.mark.asyncio
    async def test_highlights_filters_low_mentions(self, service: AnalyticsService) -> None:
        # min_mentions=3 filters out aspects with <3 total
        result = await service.get_merchant_highlights("M001", min_mentions=3)
        aspects = {item["aspect"] for item in result}
        # service has 3 total, taste has 2 total, price has 1 total
        assert "service" in aspects
        assert "taste" not in aspects

    @pytest.mark.asyncio
    async def test_highlights_top_n_limit(self, service: AnalyticsService) -> None:
        result = await service.get_merchant_highlights("M001", top_n=1)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_highlights_empty_merchant(self, service: AnalyticsService) -> None:
        result = await service.get_merchant_highlights("UNKNOWN")
        assert result == []

    @pytest.mark.asyncio
    async def test_highlights_invalid_top_n(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="top_n must be at least 1"):
            await service.get_merchant_highlights("M001", top_n=0)

    @pytest.mark.asyncio
    async def test_highlights_invalid_min_mentions(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="min_mentions must be at least 1"):
            await service.get_merchant_highlights("M001", min_mentions=0)


class TestReputationChange:
    @pytest.mark.asyncio
    async def test_reputation_change_by_day(self, service: AnalyticsService) -> None:
        result = await service.get_reputation_change("M001", granularity="day")
        assert len(result) == 2  # 2025-07-01 and 2025-07-02
        # First period: change is None
        assert result[0]["change"] is None
        assert result[0]["trend"] == "stable"
        # Second period has a change value
        assert result[1]["change"] is not None

    @pytest.mark.asyncio
    async def test_reputation_change_rates(self, service: AnalyticsService) -> None:
        result = await service.get_reputation_change("M001", granularity="day")
        # 2025-07-01: 1 pos, 1 neu, 1 neg → rate=0.3333
        assert result[0]["positive_rate"] == pytest.approx(0.3333, abs=0.001)
        # 2025-07-02: 0 pos, 0 neu, 1 neg → rate=0.0
        assert result[1]["positive_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_reputation_change_declining(self, service: AnalyticsService) -> None:
        result = await service.get_reputation_change("M001", granularity="day")
        # 0.333 → 0.0 is a decline > 5%
        assert result[1]["trend"] == "declining"

    @pytest.mark.asyncio
    async def test_reputation_change_empty_merchant(self, service: AnalyticsService) -> None:
        result = await service.get_reputation_change("UNKNOWN")
        assert result == []

    @pytest.mark.asyncio
    async def test_reputation_change_invalid_granularity(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="granularity must be one of"):
            await service.get_reputation_change("M001", granularity="year")


class TestHighlightsEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/highlights")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        assert isinstance(body["data"], list)
        if body["data"]:
            item = body["data"][0]
            assert {"aspect", "positive", "neutral", "negative", "total", "positive_rate"} <= set(
                item.keys()
            )

    def test_with_params(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/highlights?top_n=1&min_mentions=2")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) <= 1

    def test_invalid_top_n(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/highlights?top_n=0")
        assert response.status_code == 422


class TestReputationChangeEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reputation-change?granularity=day")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        assert isinstance(body["data"], list)
        if body["data"]:
            item = body["data"][0]
            assert {"period", "positive_rate", "change", "trend"} <= set(item.keys())

    def test_with_granularity(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reputation-change?granularity=day")
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 2

    def test_invalid_granularity(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/merchants/M001/analytics/reputation-change?granularity=year")
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Merchant comparison tests (TK-402-02)
# ---------------------------------------------------------------------------


class TestCompareMerchantsService:
    @pytest.mark.asyncio
    async def test_compare_two_merchants(self, service: AnalyticsService) -> None:
        result = await service.compare_merchants(["M001", "M002"])
        assert result["merchants"] == ["M001", "M002"]
        assert len(result["summary"]) == 2
        # M001: 1 pos, 1 neu, 2 neg = 4 total
        m001 = next(s for s in result["summary"] if s["merchant_id"] == "M001")
        assert m001["positive"] == 1
        assert m001["negative"] == 2
        assert m001["total"] == 4
        # M002: 1 pos, 0 neu, 0 neg = 1 total
        m002 = next(s for s in result["summary"] if s["merchant_id"] == "M002")
        assert m002["positive"] == 1
        assert m002["total"] == 1
        assert m002["positive_rate"] == 1.0

    @pytest.mark.asyncio
    async def test_compare_aspect_alignment(self, service: AnalyticsService) -> None:
        result = await service.compare_merchants(["M001", "M002"])
        aspects = {row["aspect"] for row in result["aspect_comparison"]}
        assert "taste" in aspects
        assert "service" in aspects
        # Each aspect row should have an entry per merchant
        for row in result["aspect_comparison"]:
            assert len(row["merchants"]) == 2

    @pytest.mark.asyncio
    async def test_compare_negative_reason_alignment(self, service: AnalyticsService) -> None:
        result = await service.compare_merchants(["M001", "M002"])
        # M001 has negative reviews, M002 does not
        reasons = {row["reason"] for row in result["negative_reason_comparison"]}
        assert "slow_wait" in reasons
        for row in result["negative_reason_comparison"]:
            assert len(row["merchants"]) == 2
            m002_entry = next(m for m in row["merchants"] if m["merchant_id"] == "M002")
            assert m002_entry["count"] == 0

    @pytest.mark.asyncio
    async def test_compare_with_date_range(self, service: AnalyticsService) -> None:
        result = await service.compare_merchants(
            ["M001", "M002"],
            start_date=datetime(2025, 7, 2),
            end_date=datetime(2025, 7, 3),
        )
        # Only 1 record on 2025-07-02 for M001, none for M002
        m001 = next(s for s in result["summary"] if s["merchant_id"] == "M001")
        assert m001["total"] == 1
        m002 = next(s for s in result["summary"] if s["merchant_id"] == "M002")
        assert m002["total"] == 0

    @pytest.mark.asyncio
    async def test_compare_too_few_merchants(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="at least 2 merchants"):
            await service.compare_merchants(["M001"])

    @pytest.mark.asyncio
    async def test_compare_too_many_merchants(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="at most 4 merchants"):
            await service.compare_merchants(["M001", "M002", "M003", "M004", "M005"])

    @pytest.mark.asyncio
    async def test_compare_duplicate_merchants(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="must not contain duplicates"):
            await service.compare_merchants(["M001", "M001"])

    @pytest.mark.asyncio
    async def test_compare_empty_merchant_id(self, service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="merchant_id must not be empty"):
            await service.compare_merchants(["M001", ""])

    @pytest.mark.asyncio
    async def test_compare_merchant_with_no_data(self, service: AnalyticsService) -> None:
        result = await service.compare_merchants(["M001", "M999"])
        m999 = next(s for s in result["summary"] if s["merchant_id"] == "M999")
        assert m999["total"] == 0
        assert m999["positive_rate"] == 0.0


class TestCompareMerchantsEndpoint:
    def test_success(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/analytics/compare?merchant_ids=M001&merchant_ids=M002")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        data = body["data"]
        assert data["merchants"] == ["M001", "M002"]
        assert len(data["summary"]) == 2
        assert "aspect_comparison" in data
        assert "negative_reason_comparison" in data

    def test_with_date_range(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get(
            "/api/v1/analytics/compare"
            "?merchant_ids=M001&merchant_ids=M002"
            "&start_date=2025-07-02T00:00:00"
            "&end_date=2025-07-03T00:00:00"
        )
        assert response.status_code == 200
        body = response.json()
        m001 = next(s for s in body["data"]["summary"] if s["merchant_id"] == "M001")
        assert m001["total"] == 1

    def test_too_few_merchants(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get("/api/v1/analytics/compare?merchant_ids=M001")
        assert response.status_code == 422

    def test_three_merchants(self, sample_records: list[FakeReviewAnalysis]) -> None:
        client = _create_test_client(sample_records)
        response = client.get(
            "/api/v1/analytics/compare?merchant_ids=M001&merchant_ids=M002&merchant_ids=M003"
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]["summary"]) == 3
        # M003 has no data → all zeros
        m003 = next(s for s in body["data"]["summary"] if s["merchant_id"] == "M003")
        assert m003["total"] == 0
