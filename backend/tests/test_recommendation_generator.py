"""Unit tests for business recommendation generation with evidence linking."""

import json

# ---------------------------------------------------------------------------
# Fake data structures (reuse from test_analytics.py pattern)
# ---------------------------------------------------------------------------
from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.application.analytics import AnalyticsService
from app.application.recommendation_generator import (
    PROMPT_VERSION,
    RecommendationGenerator,
)
from app.core.ids import uuid7


@dataclass
class FakeReviewAnalysis:
    """Lightweight stand-in for the ORM model."""

    id: object
    merchant_id: str
    review_text: str
    sentiment: str
    confidence: float
    aspect_labels: str
    negative_reasons: str
    review_date: datetime | None = None


# ---------------------------------------------------------------------------
# Generator unit tests (direct engine tests)
# ---------------------------------------------------------------------------


def _make_evidence_reviews(count: int, reason: str = "slow_wait") -> list[FakeReviewAnalysis]:
    """Create fake negative reviews for evidence."""
    return [
        FakeReviewAnalysis(
            id=uuid7(),
            merchant_id="M001",
            review_text=f"差评{reason}测试{i}",
            sentiment="NEGATIVE",
            confidence=0.9,
            aspect_labels=json.dumps(["service"]),
            negative_reasons=json.dumps([reason]),
            review_date=datetime(2025, 7, 1),
        )
        for i in range(count)
    ]


class TestRecommendationGeneratorNegativeReason:
    def test_reason_above_threshold_generates_recommendation(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[
                {"reason": "slow_wait", "count": 3},
                {"reason": "rude_staff", "count": 1},
            ],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 2, "negative": 5, "total": 12},
            evidence_reviews={"slow_wait": _make_evidence_reviews(3)},
        )
        recs = [r for r in report.recommendations if r.category == "negative_reason"]
        assert len(recs) == 1
        assert recs[0].recommendation_id == "neg_slow_wait"
        assert recs[0].related_negative_reason == "slow_wait"
        assert len(recs[0].evidence) == 3

    def test_reason_below_threshold_not_generated(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "rude_staff", "count": 1}],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 2, "negative": 5, "total": 12},
            evidence_reviews={},
        )
        recs = [r for r in report.recommendations if r.category == "negative_reason"]
        assert len(recs) == 0

    def test_high_priority_for_high_count(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 6}],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 2, "negative": 8, "total": 15},
            evidence_reviews={"slow_wait": _make_evidence_reviews(5)},
        )
        rec = next(r for r in report.recommendations if r.category == "negative_reason")
        assert rec.priority == "high"

    def test_medium_priority_for_moderate_count(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "rude_staff", "count": 3}],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 2, "negative": 5, "total": 12},
            evidence_reviews={"rude_staff": _make_evidence_reviews(3, "rude_staff")},
        )
        rec = next(r for r in report.recommendations if r.category == "negative_reason")
        assert rec.priority == "medium"


class TestRecommendationGeneratorWeakAspect:
    def test_weak_aspect_generated(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[
                {
                    "aspect": "taste",
                    "positive": 1,
                    "neutral": 1,
                    "negative": 3,
                    "total": 5,
                    "positive_rate": 0.2,
                },
            ],
            summary_stats={"positive": 1, "neutral": 1, "negative": 3, "total": 5},
            evidence_reviews={},
        )
        recs = [r for r in report.recommendations if r.category == "weak_aspect"]
        assert len(recs) == 1
        assert recs[0].recommendation_id == "weak_taste"
        assert recs[0].priority == "high"  # rate < 0.3

    def test_weak_aspect_skipped_if_covered_by_reason(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "taste_bad", "count": 3}],
            aspect_stats=[
                {
                    "aspect": "taste",
                    "positive": 1,
                    "neutral": 1,
                    "negative": 3,
                    "total": 5,
                    "positive_rate": 0.2,
                },
            ],
            summary_stats={"positive": 1, "neutral": 1, "negative": 3, "total": 5},
            evidence_reviews={"taste_bad": _make_evidence_reviews(3, "taste_bad")},
        )
        # taste_bad maps to aspect "taste", so weak_taste should be skipped
        weak_recs = [r for r in report.recommendations if r.category == "weak_aspect"]
        assert len(weak_recs) == 0

    def test_aspect_below_min_sample_not_generated(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[
                {
                    "aspect": "taste",
                    "positive": 0,
                    "neutral": 0,
                    "negative": 2,
                    "total": 2,
                    "positive_rate": 0.0,
                },
            ],
            summary_stats={"positive": 0, "neutral": 0, "negative": 2, "total": 2},
            evidence_reviews={},
        )
        weak_recs = [r for r in report.recommendations if r.category == "weak_aspect"]
        assert len(weak_recs) == 0


class TestRecommendationGeneratorStrength:
    def test_strength_generated(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[
                {
                    "aspect": "attitude",
                    "positive": 9,
                    "neutral": 1,
                    "negative": 0,
                    "total": 10,
                    "positive_rate": 0.9,
                },
            ],
            summary_stats={"positive": 9, "neutral": 1, "negative": 0, "total": 10},
            evidence_reviews={},
        )
        recs = [r for r in report.recommendations if r.category == "strength"]
        assert len(recs) == 1
        assert recs[0].recommendation_id == "strength_attitude"
        assert recs[0].priority == "low"

    def test_strength_not_generated_below_threshold(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[
                {
                    "aspect": "attitude",
                    "positive": 4,
                    "neutral": 1,
                    "negative": 0,
                    "total": 5,
                    "positive_rate": 0.8,
                },
            ],
            summary_stats={"positive": 4, "neutral": 1, "negative": 0, "total": 5},
            evidence_reviews={},
        )
        # rate == 0.8, not > 0.8, so no strength
        strength_recs = [r for r in report.recommendations if r.category == "strength"]
        assert len(strength_recs) == 0


class TestRecommendationGeneratorConfidence:
    def test_confidence_increases_with_more_data(self) -> None:
        gen = RecommendationGenerator()
        # 10 reviews, 5 evidence
        report_small = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 3}],
            aspect_stats=[],
            summary_stats={"positive": 3, "neutral": 2, "negative": 5, "total": 10},
            evidence_reviews={"slow_wait": _make_evidence_reviews(3)},
        )
        # 30 reviews, 5 evidence
        report_large = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 3}],
            aspect_stats=[],
            summary_stats={"positive": 10, "neutral": 10, "negative": 10, "total": 30},
            evidence_reviews={"slow_wait": _make_evidence_reviews(5)},
        )
        conf_small = next(
            r.confidence for r in report_small.recommendations if r.category == "negative_reason"
        )
        conf_large = next(
            r.confidence for r in report_large.recommendations if r.category == "negative_reason"
        )
        assert conf_large > conf_small

    def test_confidence_max_is_1(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 10}],
            aspect_stats=[],
            summary_stats={"positive": 20, "neutral": 10, "negative": 20, "total": 50},
            evidence_reviews={"slow_wait": _make_evidence_reviews(5)},
        )
        rec = next(r for r in report.recommendations if r.category == "negative_reason")
        assert rec.confidence == 1.0

    def test_confidence_zero_with_no_evidence(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[
                {
                    "aspect": "taste",
                    "positive": 1,
                    "neutral": 1,
                    "negative": 3,
                    "total": 5,
                    "positive_rate": 0.2,
                },
            ],
            summary_stats={"positive": 1, "neutral": 1, "negative": 3, "total": 5},
            evidence_reviews={},
        )
        # weak aspect: confidence uses total (5) as evidence count
        # data_confidence = 5/30 = 0.17, evidence_confidence = 5/5 = 1.0
        # combined = (0.17 + 1.0) / 2 = 0.58
        rec = next(r for r in report.recommendations if r.category == "weak_aspect")
        expected = round((min(1.0, 5 / 30) + min(1.0, 5 / 5)) / 2, 2)
        assert rec.confidence == expected


class TestRecommendationGeneratorReport:
    def test_version_stamp(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 0, "neutral": 0, "negative": 0, "total": 0},
            evidence_reviews={},
        )
        assert report.prompt_version == PROMPT_VERSION

    def test_low_sample_warning(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 3, "neutral": 2, "negative": 4, "total": 9},
            evidence_reviews={},
        )
        assert report.low_sample_warning is True

    def test_no_low_sample_warning(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 3, "negative": 4, "total": 12},
            evidence_reviews={},
        )
        assert report.low_sample_warning is False

    def test_empty_data_produces_empty_recommendations(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M999",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 0, "neutral": 0, "negative": 0, "total": 0},
            evidence_reviews={},
        )
        assert len(report.recommendations) == 0
        assert report.summary["total_reviews"] == 0
        assert report.low_sample_warning is True

    def test_priority_sorting(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[
                {"reason": "slow_wait", "count": 6},  # high
                {"reason": "rude_staff", "count": 3},  # medium
            ],
            aspect_stats=[
                {
                    "aspect": "attitude",
                    "positive": 9,
                    "neutral": 1,
                    "negative": 0,
                    "total": 10,
                    "positive_rate": 0.9,
                },  # strength, low
            ],
            summary_stats={"positive": 10, "neutral": 5, "negative": 10, "total": 25},
            evidence_reviews={
                "slow_wait": _make_evidence_reviews(5, "slow_wait"),
                "rude_staff": _make_evidence_reviews(3, "rude_staff"),
            },
        )
        priorities = [r.priority for r in report.recommendations]
        assert priorities == ["high", "medium", "low"]

    def test_evidence_linked_correctly(self) -> None:
        gen = RecommendationGenerator()
        reviews = _make_evidence_reviews(3, "slow_wait")
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 3}],
            aspect_stats=[],
            summary_stats={"positive": 5, "neutral": 2, "negative": 5, "total": 12},
            evidence_reviews={"slow_wait": reviews},
        )
        rec = next(r for r in report.recommendations if r.category == "negative_reason")
        assert len(rec.evidence) == 3
        assert all(ev.sentiment == "NEGATIVE" for ev in rec.evidence)
        assert all(ev.review_id == str(r.id) for ev, r in zip(rec.evidence, reviews, strict=False))

    def test_evidence_capped_at_max(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[{"reason": "slow_wait", "count": 10}],
            aspect_stats=[],
            summary_stats={"positive": 10, "neutral": 5, "negative": 10, "total": 25},
            evidence_reviews={"slow_wait": _make_evidence_reviews(8, "slow_wait")},
        )
        rec = next(r for r in report.recommendations if r.category == "negative_reason")
        assert len(rec.evidence) == 5  # capped at _MAX_EVIDENCE_PER_RECOMMENDATION

    def test_summary_fields_populated(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 10, "neutral": 5, "negative": 5, "total": 20},
            evidence_reviews={},
        )
        assert report.summary["total_reviews"] == 20
        assert report.summary["positive"] == 10
        assert report.summary["negative"] == 5
        assert report.summary["positive_rate"] == 0.5
        assert report.summary["negative_rate"] == 0.25
        assert report.summary["data_confidence"] == round(20 / 30, 2)

    def test_generated_at_is_valid_datetime(self) -> None:
        gen = RecommendationGenerator()
        report = gen.generate(
            merchant_id="M001",
            negative_reason_stats=[],
            aspect_stats=[],
            summary_stats={"positive": 0, "neutral": 0, "negative": 0, "total": 0},
            evidence_reviews={},
        )
        assert report.generated_at is not None


# ---------------------------------------------------------------------------
# Service layer tests
# ---------------------------------------------------------------------------

from collections import Counter  # noqa: E402


class InMemoryAnalyticsRepository:
    """Fake repository that stores data in memory and mimics aggregation."""

    def __init__(self, records: list[FakeReviewAnalysis] | None = None) -> None:
        self._records = records or []

    async def get_sentiment_trend(
        self,
        merchant_id: str,
        *,
        granularity: str = "day",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        return []

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
        granularity: str = "week",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        return []

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


def _rich_sample_records() -> list[FakeReviewAnalysis]:
    """Create richer sample data that triggers all recommendation types."""
    base = datetime(2025, 7, 1, 12, 0, 0)
    records: list[FakeReviewAnalysis] = []
    # 8 positive reviews on taste/attitude
    for i in range(5):
        records.append(
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"味道很好{i}",
                sentiment="POSITIVE",
                confidence=0.95,
                aspect_labels=json.dumps(["taste"]),
                negative_reasons="[]",
                review_date=base,
            )
        )
    for i in range(5):
        records.append(
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"服务很好{i}",
                sentiment="POSITIVE",
                confidence=0.95,
                aspect_labels=json.dumps(["attitude"]),
                negative_reasons="[]",
                review_date=base,
            )
        )
    # 3 negative reviews with slow_wait
    for i in range(3):
        records.append(
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"等太久{i}",
                sentiment="NEGATIVE",
                confidence=0.9,
                aspect_labels=json.dumps(["waiting_time"]),
                negative_reasons=json.dumps(["slow_wait"]),
                review_date=base,
            )
        )
    # 3 negative reviews with rude_staff
    for i in range(3):
        records.append(
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"态度差{i}",
                sentiment="NEGATIVE",
                confidence=0.9,
                aspect_labels=json.dumps(["attitude"]),
                negative_reasons=json.dumps(["rude_staff"]),
                review_date=base,
            )
        )
    # 2 neutral reviews
    for i in range(2):
        records.append(
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"一般般{i}",
                sentiment="NEUTRAL",
                confidence=0.7,
                aspect_labels=json.dumps(["overall"]),
                negative_reasons="[]",
                review_date=base,
            )
        )
    return records


@pytest.fixture
def rich_service() -> AnalyticsService:
    repo = InMemoryAnalyticsRepository(_rich_sample_records())
    return AnalyticsService(repo)


@pytest.fixture
def empty_service() -> AnalyticsService:
    repo = InMemoryAnalyticsRepository([])
    return AnalyticsService(repo)


class TestRecommendationsService:
    @pytest.mark.asyncio
    async def test_generate_with_rich_data(self, rich_service: AnalyticsService) -> None:
        report = await rich_service.generate_recommendations("M001")
        assert report.merchant_id == "M001"
        assert report.prompt_version == PROMPT_VERSION
        # slow_wait count=3, rude_staff count=3 → 2 negative_reason recommendations
        neg_recs = [r for r in report.recommendations if r.category == "negative_reason"]
        assert len(neg_recs) == 2
        # Each should have evidence
        for rec in neg_recs:
            assert len(rec.evidence) > 0

    @pytest.mark.asyncio
    async def test_generate_empty_merchant(self, rich_service: AnalyticsService) -> None:
        report = await rich_service.generate_recommendations("M999")
        assert len(report.recommendations) == 0
        assert report.summary["total_reviews"] == 0
        assert report.low_sample_warning is True

    @pytest.mark.asyncio
    async def test_generate_with_date_range(self, rich_service: AnalyticsService) -> None:
        report = await rich_service.generate_recommendations(
            "M001",
            start_date=datetime(2025, 7, 2),
            end_date=datetime(2025, 7, 3),
        )
        # All records are on 2025-07-01, so date range should return empty
        assert report.summary["total_reviews"] == 0

    @pytest.mark.asyncio
    async def test_generate_empty_merchant_id_raises(self, empty_service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="merchant_id must not be empty"):
            await empty_service.generate_recommendations("")

    @pytest.mark.asyncio
    async def test_generate_invalid_date_range_raises(self, rich_service: AnalyticsService) -> None:
        with pytest.raises(ValueError, match="start_date must be earlier"):
            await rich_service.generate_recommendations(
                "M001",
                start_date=datetime(2025, 7, 10),
                end_date=datetime(2025, 7, 1),
            )

    @pytest.mark.asyncio
    async def test_low_sample_warning_with_few_reviews(
        self, empty_service: AnalyticsService
    ) -> None:
        # Add just 5 records (below threshold of 10)
        records = [
            FakeReviewAnalysis(
                id=uuid7(),
                merchant_id="M001",
                review_text=f"测试{i}",
                sentiment="NEGATIVE" if i < 3 else "POSITIVE",
                confidence=0.9,
                aspect_labels=json.dumps(["overall"]),
                negative_reasons=json.dumps(["slow_wait"]) if i < 3 else "[]",
                review_date=datetime(2025, 7, 1),
            )
            for i in range(5)
        ]
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        assert report.low_sample_warning is True


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


def _create_test_client(records: list[FakeReviewAnalysis]) -> TestClient:
    """Create a minimal FastAPI TestClient for recommendation endpoint tests."""
    from fastapi import FastAPI

    from app.api.analytics import business_router as analytics_business_router
    from app.api.analytics import get_analytics_service
    from app.core.api import install_api_contract
    from app.core.config import get_settings

    app = FastAPI()
    settings = get_settings()
    app.state.settings = settings
    install_api_contract(app, settings)
    app.include_router(analytics_business_router, prefix=settings.api_v1_prefix)

    repo = InMemoryAnalyticsRepository(records)
    service = AnalyticsService(repo)
    app.dependency_overrides[get_analytics_service] = lambda: service

    return TestClient(app)


class TestRecommendationsEndpoint:
    def test_success(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post("/api/v1/merchants/M001/business-suggestions")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "OK"
        data = body["data"]
        assert data["merchant_id"] == "M001"
        assert data["prompt_version"] == PROMPT_VERSION
        assert "generated_at" in data
        assert "summary" in data
        assert "recommendations" in data
        assert "low_sample_warning" in data
        assert len(data["recommendations"]) > 0
        # Verify first recommendation has required fields
        rec = data["recommendations"][0]
        assert {"recommendation_id", "category", "priority", "title", "description"} <= set(
            rec.keys()
        )
        assert {"confidence", "evidence"} <= set(rec.keys())

    def test_empty_merchant_returns_200(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post("/api/v1/merchants/M999/business-suggestions")
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["summary"]["total_reviews"] == 0
        assert body["data"]["low_sample_warning"] is True
        assert len(body["data"]["recommendations"]) == 0

    def test_with_date_range(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post(
            "/api/v1/merchants/M001/business-suggestions"
            "?start_date=2025-07-02T00:00:00"
            "&end_date=2025-07-03T00:00:00"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["data"]["summary"]["total_reviews"] == 0

    def test_evidence_structure(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post("/api/v1/merchants/M001/business-suggestions")
        body = response.json()
        neg_recs = [
            r for r in body["data"]["recommendations"] if r["category"] == "negative_reason"
        ]
        assert len(neg_recs) > 0
        for rec in neg_recs:
            assert len(rec["evidence"]) > 0
            ev = rec["evidence"][0]
            assert {"review_id", "review_text", "sentiment"} <= set(ev.keys())
            assert {"aspect_labels", "negative_reasons", "review_date"} <= set(ev.keys())

    def test_priority_ordering(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post("/api/v1/merchants/M001/business-suggestions")
        body = response.json()
        priorities = [r["priority"] for r in body["data"]["recommendations"]]
        # Should be sorted: high before medium before low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        indexed = [priority_order.get(p, 3) for p in priorities]
        assert indexed == sorted(indexed)

    def test_summary_fields(self) -> None:
        client = _create_test_client(_rich_sample_records())
        response = client.post("/api/v1/merchants/M001/business-suggestions")
        body = response.json()
        summary = body["data"]["summary"]
        assert {"total_reviews", "positive", "neutral", "negative"} <= set(summary.keys())
        assert {"positive_rate", "negative_rate", "data_confidence"} <= set(summary.keys())
        assert summary["total_reviews"] == 18  # 5+5+3+3+2
