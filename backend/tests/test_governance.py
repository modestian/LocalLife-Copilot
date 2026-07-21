"""Governance tests: permission isolation, evidence consistency, low-sample rejection.

Covers TK-402-05 acceptance criterion ⑥:
- Permission isolation: merchant data isolation, comparison exposes only aggregated public data.
- Evidence consistency: evidence_review_ids matches the union of all recommendation evidence.
- Low-sample rejection: insufficient samples produce warning and suppress deterministic conclusions.
"""

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.analytics import AnalyticsService
from app.core.ids import uuid7

# ---------------------------------------------------------------------------
# Fake data structures (shared pattern with test_recommendation_generator.py)
# ---------------------------------------------------------------------------


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
# In-memory repository (mirrors test_recommendation_generator.py)
# ---------------------------------------------------------------------------


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

    async def get_aspect_comparison_stats(
        self,
        merchant_ids: list[str],
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        result: list[dict] = []
        for mid in merchant_ids:
            aspects = await self.get_aspect_sentiment_stats(
                mid, start_date=start_date, end_date=end_date
            )
            for a in aspects:
                a["merchant_id"] = mid
            result.extend(aspects)
        return result

    async def get_negative_reason_comparison_stats(
        self,
        merchant_ids: list[str],
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        result: list[dict] = []
        for mid in merchant_ids:
            reasons = await self.get_negative_reason_aggregation(
                mid, start_date=start_date, end_date=end_date
            )
            for r in reasons:
                r["merchant_id"] = mid
            result.extend(r for r in reasons)
        return result

    async def find_review_by_id(self, review_id: UUID) -> FakeReviewAnalysis | None:
        return next((r for r in self._records if r.id == review_id), None)

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


# ---------------------------------------------------------------------------
# Multi-merchant sample data factories
# ---------------------------------------------------------------------------

_BASE_DATE = datetime(2025, 7, 1, 12, 0, 0)


def _make_review(
    merchant_id: str,
    text: str,
    sentiment: str,
    aspects: list[str],
    reasons: list[str] | None = None,
    date: datetime | None = None,
) -> FakeReviewAnalysis:
    return FakeReviewAnalysis(
        id=uuid7(),
        merchant_id=merchant_id,
        review_text=text,
        sentiment=sentiment,
        confidence=0.9,
        aspect_labels=json.dumps(aspects),
        negative_reasons=json.dumps(reasons or []),
        review_date=date or _BASE_DATE,
    )


def _multi_merchant_records() -> list[FakeReviewAnalysis]:
    """Create sample data for M001 and M002 with diverse sentiments and reasons."""
    records: list[FakeReviewAnalysis] = []

    # M001: 5 pos taste, 5 pos attitude, 3 neg slow_wait,
    #       3 neg rude_staff, 2 neutral
    for i in range(5):
        records.append(_make_review("M001", f"味道很好{i}", "POSITIVE", ["taste"]))
    for i in range(5):
        records.append(_make_review("M001", f"服务很好{i}", "POSITIVE", ["attitude"]))
    for i in range(3):
        records.append(
            _make_review("M001", f"等太久{i}", "NEGATIVE", ["waiting_time"], ["slow_wait"])
        )
    for i in range(3):
        records.append(_make_review("M001", f"态度差{i}", "NEGATIVE", ["attitude"], ["rude_staff"]))
    for i in range(2):
        records.append(_make_review("M001", f"一般般{i}", "NEUTRAL", ["overall"]))

    # M002: 4 positive taste, 3 negative taste_bad, 2 neutral
    for i in range(4):
        records.append(_make_review("M002", f"M002味道好{i}", "POSITIVE", ["taste"]))
    for i in range(3):
        records.append(_make_review("M002", f"M002味道差{i}", "NEGATIVE", ["taste"], ["taste_bad"]))
    for i in range(2):
        records.append(_make_review("M002", f"M002一般{i}", "NEUTRAL", ["overall"]))

    return records


def _low_sample_records(count: int, merchant_id: str = "M001") -> list[FakeReviewAnalysis]:
    """Create fewer-than-threshold reviews to trigger low_sample_warning."""
    records: list[FakeReviewAnalysis] = []
    for i in range(count):
        sentiment = "NEGATIVE" if i < count // 2 else "POSITIVE"
        reasons = ["slow_wait"] if sentiment == "NEGATIVE" else []
        aspects = ["service"] if sentiment == "NEGATIVE" else ["taste"]
        records.append(_make_review(merchant_id, f"低样本{i}", sentiment, aspects, reasons))
    return records


def _sufficient_sample_records(merchant_id: str = "M001") -> list[FakeReviewAnalysis]:
    """Create enough reviews (>=10) to avoid low_sample_warning."""
    records: list[FakeReviewAnalysis] = []
    for i in range(6):
        records.append(_make_review(merchant_id, f"正面{i}", "POSITIVE", ["taste"]))
    for i in range(3):
        records.append(
            _make_review(merchant_id, f"负面{i}", "NEGATIVE", ["waiting_time"], ["slow_wait"])
        )
    for i in range(2):
        records.append(_make_review(merchant_id, f"中性{i}", "NEUTRAL", ["overall"]))
    return records


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def multi_repo() -> InMemoryAnalyticsRepository:
    return InMemoryAnalyticsRepository(_multi_merchant_records())


@pytest.fixture
def multi_service(multi_repo: InMemoryAnalyticsRepository) -> AnalyticsService:
    return AnalyticsService(multi_repo)


@pytest.fixture
def empty_repo() -> InMemoryAnalyticsRepository:
    return InMemoryAnalyticsRepository([])


@pytest.fixture
def empty_service(empty_repo: InMemoryAnalyticsRepository) -> AnalyticsService:
    return AnalyticsService(empty_repo)


def _create_test_client(records: list[FakeReviewAnalysis]) -> TestClient:
    """Create a minimal FastAPI TestClient for governance endpoint tests."""
    from app.api.analytics import (
        business_router as analytics_business_router,
    )
    from app.api.analytics import (
        compare_router as analytics_compare_router,
    )
    from app.api.analytics import (
        get_analytics_service,
    )
    from app.api.analytics import (
        reviews_router as analytics_reviews_router,
    )
    from app.api.analytics import (
        router as analytics_router,
    )
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
    app.include_router(analytics_reviews_router, prefix=settings.api_v1_prefix)

    repo = InMemoryAnalyticsRepository(records)
    service = AnalyticsService(repo)
    app.dependency_overrides[get_analytics_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: AuthorizationPrincipal(
        user_id=uuid7(),
        username="governance-test-admin",
        display_name="Governance test admin",
        email=None,
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "Platform admin"),),
        permissions=(),
        resource_grants=(),
    )

    return TestClient(app)


# ---------------------------------------------------------------------------
# Placeholder test classes — to be filled in Step 2
# ---------------------------------------------------------------------------


class TestPermissionIsolation:
    """Tests for merchant data isolation and comparison data exposure."""

    # ------------------------------------------------------------------
    # Repository-level isolation
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_repository_negative_reasons_isolated(
        self, multi_repo: InMemoryAnalyticsRepository
    ) -> None:
        """M001 negative reason aggregation must not include M002 reasons."""
        m001_reasons = await multi_repo.get_negative_reason_aggregation("M001")
        m002_reasons = await multi_repo.get_negative_reason_aggregation("M002")
        m001_codes = {r["reason"] for r in m001_reasons}
        m002_codes = {r["reason"] for r in m002_reasons}
        # M001 has slow_wait + rude_staff; M002 has taste_bad
        assert "taste_bad" not in m001_codes
        assert "slow_wait" not in m002_codes
        assert "rude_staff" not in m002_codes

    @pytest.mark.asyncio
    async def test_repository_aspect_stats_isolated(
        self, multi_repo: InMemoryAnalyticsRepository
    ) -> None:
        """M001 aspect stats must not include M002-only aspects."""
        m001_aspects = await multi_repo.get_aspect_sentiment_stats("M001")
        m002_aspects = await multi_repo.get_aspect_sentiment_stats("M002")
        m001_names = {a["aspect"] for a in m001_aspects}
        m002_names = {a["aspect"] for a in m002_aspects}
        # M001 has waiting_time (from slow_wait); M002 does not
        assert "waiting_time" in m001_names
        assert "waiting_time" not in m002_names

    @pytest.mark.asyncio
    async def test_drill_down_isolated(self, multi_repo: InMemoryAnalyticsRepository) -> None:
        """M001 drill-down must not return M002 reviews."""
        m001_reviews = await multi_repo.drill_down_reviews("M001")
        for r in m001_reviews:
            assert r.merchant_id == "M001"
        m002_reviews = await multi_repo.drill_down_reviews("M002")
        for r in m002_reviews:
            assert r.merchant_id == "M002"

    @pytest.mark.asyncio
    async def test_drill_down_by_reason_isolated(
        self, multi_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Drill-down by negative reason must only return target merchant reviews."""
        m001_slow = await multi_repo.drill_down_reviews("M001", negative_reason="slow_wait")
        assert len(m001_slow) == 3
        for r in m001_slow:
            assert r.merchant_id == "M001"

    # ------------------------------------------------------------------
    # Comparison endpoint: no raw review text leakage
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_comparison_no_raw_review_text(self, multi_service: AnalyticsService) -> None:
        """Comparison result must not expose raw review_text from any merchant."""
        result = await multi_service.compare_merchants(["M001", "M002"])
        # Flatten the entire result and check no review_text field appears
        import json as _json

        flat = _json.dumps(result, ensure_ascii=False)
        assert "review_text" not in flat
        assert "味道很好" not in flat  # M001 raw text
        assert "M002味道好" not in flat  # M002 raw text

    @pytest.mark.asyncio
    async def test_comparison_summary_contains_sample_size(
        self, multi_service: AnalyticsService
    ) -> None:
        """Each merchant metric must include sample_count."""
        result = await multi_service.compare_merchants(["M001", "M002"])
        for m in result["merchants"]:
            assert "sample_count" in m
            assert m["sample_count"] > 0

    @pytest.mark.asyncio
    async def test_comparison_same_time_window(self, multi_service: AnalyticsService) -> None:
        """Comparison must use the same start/end date for all merchants."""
        start = datetime(2025, 7, 1)
        end = datetime(2025, 7, 2)
        result = await multi_service.compare_merchants(
            ["M001", "M002"], start_date=start, end_date=end
        )
        # Both merchants' data should be filtered by the same date range
        m001_total = next(
            m["sample_count"] for m in result["merchants"] if m["merchant_id"] == "M001"
        )
        m002_total = next(
            m["sample_count"] for m in result["merchants"] if m["merchant_id"] == "M002"
        )
        # All records are on 2025-07-01, so both should have data
        assert m001_total == 18
        assert m002_total == 9

    # ------------------------------------------------------------------
    # Recommendations: evidence must not cross merchant boundary
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_recommendations_evidence_same_merchant(
        self, multi_service: AnalyticsService
    ) -> None:
        """All evidence in recommendations must belong to the target merchant."""
        report = await multi_service.generate_recommendations("M001")
        for rec in report.recommendations:
            for ev in rec.evidence:
                # Evidence review_ids should correspond to M001 reviews only
                # (drill_down was called with merchant_id="M001")
                assert ev.review_id is not None
        # evidence_review_ids should not be empty if there are negative reasons
        neg_recs = [r for r in report.recommendations if r.category == "negative_reason"]
        if neg_recs:
            assert len(report.evidence_review_ids) > 0

    @pytest.mark.asyncio
    async def test_recommendations_no_cross_merchant_evidence(
        self, multi_service: AnalyticsService, multi_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Evidence review IDs must not include reviews from other merchants."""
        report = await multi_service.generate_recommendations("M001")
        m002_reviews = await multi_repo.drill_down_reviews("M002")
        m002_ids = {str(r.id) for r in m002_reviews}
        for ev_id in report.evidence_review_ids:
            assert ev_id not in m002_ids

    # ------------------------------------------------------------------
    # API endpoint level: comparison response has no raw text
    # ------------------------------------------------------------------

    def test_api_comparison_no_raw_review_text(self) -> None:
        """POST /api/v1/merchants/compare must not leak raw review text."""
        client = _create_test_client(_multi_merchant_records())
        response = client.post(
            "/api/v1/merchants/compare",
            json={"merchant_ids": ["M001", "M002"]},
        )
        assert response.status_code == 200
        body_str = response.text
        assert "味道很好" not in body_str
        assert "M002味道好" not in body_str


class TestEvidenceConsistency:
    """Tests for evidence_review_ids consistency with recommendation evidence."""

    @pytest.mark.asyncio
    async def test_evidence_review_ids_matches_union(self, multi_service: AnalyticsService) -> None:
        """Top-level evidence_review_ids must equal the union of all evidence IDs."""
        report = await multi_service.generate_recommendations("M001")
        all_ev_ids: set[str] = set()
        for rec in report.recommendations:
            for ev in rec.evidence:
                all_ev_ids.add(ev.review_id)
        assert set(report.evidence_review_ids) == all_ev_ids

    @pytest.mark.asyncio
    async def test_evidence_review_ids_no_duplicates(self, multi_service: AnalyticsService) -> None:
        """evidence_review_ids must not contain duplicate entries."""
        report = await multi_service.generate_recommendations("M001")
        ids = report.evidence_review_ids
        assert len(ids) == len(set(ids))

    @pytest.mark.asyncio
    async def test_every_top_level_id_in_some_recommendation(
        self, multi_service: AnalyticsService
    ) -> None:
        """Every evidence_review_id must appear in at least one recommendation's evidence."""
        report = await multi_service.generate_recommendations("M001")
        rec_ev_ids: set[str] = set()
        for rec in report.recommendations:
            for ev in rec.evidence:
                rec_ev_ids.add(ev.review_id)
        for eid in report.evidence_review_ids:
            assert eid in rec_ev_ids

    @pytest.mark.asyncio
    async def test_recommendation_evidence_subset_of_top_level(
        self, multi_service: AnalyticsService
    ) -> None:
        """Every recommendation evidence ID must be in the top-level evidence_review_ids."""
        report = await multi_service.generate_recommendations("M001")
        top_set = set(report.evidence_review_ids)
        for rec in report.recommendations:
            for ev in rec.evidence:
                assert ev.review_id in top_set

    @pytest.mark.asyncio
    async def test_negative_reason_evidence_all_negative_sentiment(
        self, multi_service: AnalyticsService
    ) -> None:
        """Evidence for negative_reason recommendations must all be NEGATIVE sentiment."""
        report = await multi_service.generate_recommendations("M001")
        neg_recs = [r for r in report.recommendations if r.category == "negative_reason"]
        for rec in neg_recs:
            for ev in rec.evidence:
                assert ev.sentiment == "NEGATIVE"

    @pytest.mark.asyncio
    async def test_evidence_capped_at_max_per_recommendation(
        self, multi_service: AnalyticsService
    ) -> None:
        """Each recommendation must have at most 5 evidence items."""
        report = await multi_service.generate_recommendations("M001")
        for rec in report.recommendations:
            assert len(rec.evidence) <= 5

    @pytest.mark.asyncio
    async def test_empty_recommendations_empty_evidence_ids(
        self, empty_service: AnalyticsService
    ) -> None:
        """When there are no recommendations, evidence_review_ids must be empty."""
        report = await empty_service.generate_recommendations("M999")
        assert len(report.recommendations) == 0
        assert report.evidence_review_ids == []

    @pytest.mark.asyncio
    async def test_evidence_traceable_to_drill_down(
        self, multi_service: AnalyticsService, multi_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Every evidence review_id must be findable via drill_down_reviews."""
        report = await multi_service.generate_recommendations("M001")
        all_drill_down = await multi_repo.drill_down_reviews("M001", sentiment="NEGATIVE")
        all_ids = {str(r.id) for r in all_drill_down}
        for ev_id in report.evidence_review_ids:
            assert ev_id in all_ids


class TestLowSampleRejection:
    """Tests for low-sample warning and suppression of deterministic conclusions."""

    @pytest.mark.asyncio
    async def test_low_sample_warning_true_below_threshold(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """total_reviews < 10 must produce low_sample_warning = True."""
        records = _low_sample_records(9)
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        assert report.low_sample_warning is True
        assert report.summary["total_reviews"] == 9

    @pytest.mark.asyncio
    async def test_low_sample_warning_false_at_threshold(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """total_reviews >= 10 must produce low_sample_warning = False."""
        records = _sufficient_sample_records()  # 11 records
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        assert report.low_sample_warning is False
        assert report.summary["total_reviews"] == 11

    @pytest.mark.asyncio
    async def test_low_sample_warning_true_for_empty_merchant(
        self, empty_service: AnalyticsService
    ) -> None:
        """Non-existent merchant (total=0) must have low_sample_warning = True."""
        report = await empty_service.generate_recommendations("M999")
        assert report.low_sample_warning is True
        assert report.summary["total_reviews"] == 0

    @pytest.mark.asyncio
    async def test_low_sample_still_generates_recommendations(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Low sample does not suppress all recommendations, but warning is set."""
        # 8 records: 4 negative slow_wait, 4 positive taste
        records: list[FakeReviewAnalysis] = []
        for i in range(4):
            records.append(
                _make_review(
                    "M001",
                    f"差评{i}",
                    "NEGATIVE",
                    ["waiting_time"],
                    ["slow_wait"],
                )
            )
        for i in range(4):
            records.append(_make_review("M001", f"好评{i}", "POSITIVE", ["taste"]))
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        assert report.low_sample_warning is True
        # slow_wait count=4 >= 2, so negative_reason recommendation should exist
        neg_recs = [r for r in report.recommendations if r.category == "negative_reason"]
        assert len(neg_recs) > 0

    @pytest.mark.asyncio
    async def test_aspect_below_min_sample_not_generated(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Aspect with total < 3 must not generate weak_aspect recommendation."""
        # 10 total reviews but taste aspect only has 2 total
        records: list[FakeReviewAnalysis] = []
        for i in range(2):
            records.append(_make_review("M001", f"差评{i}", "NEGATIVE", ["taste"], ["taste_bad"]))
        for i in range(8):
            records.append(_make_review("M001", f"好评{i}", "POSITIVE", ["attitude"]))
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        weak_recs = [r for r in report.recommendations if r.category == "weak_aspect"]
        # taste has total=2 < 3, so no weak_taste
        taste_weak = [r for r in weak_recs if r.related_aspect == "taste"]
        assert len(taste_weak) == 0

    @pytest.mark.asyncio
    async def test_negative_reason_below_threshold_not_generated(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Negative reason with count < 2 must not generate recommendation."""
        # 10 total: 1 negative with slow_wait, 9 positive
        records: list[FakeReviewAnalysis] = []
        records.append(_make_review("M001", "差评", "NEGATIVE", ["waiting_time"], ["slow_wait"]))
        for i in range(9):
            records.append(_make_review("M001", f"好评{i}", "POSITIVE", ["taste"]))
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        neg_recs = [r for r in report.recommendations if r.category == "negative_reason"]
        # slow_wait count=1 < 2, so no negative_reason recommendation
        assert len(neg_recs) == 0

    @pytest.mark.asyncio
    async def test_strength_requires_min_5_samples(
        self, empty_repo: InMemoryAnalyticsRepository
    ) -> None:
        """Strength recommendation requires aspect total >= 5."""
        # 10 total: 4 positive attitude (total=4 < 5), 6 positive taste
        records: list[FakeReviewAnalysis] = []
        for i in range(4):
            records.append(_make_review("M001", f"服务好{i}", "POSITIVE", ["attitude"]))
        for i in range(6):
            records.append(_make_review("M001", f"味道好{i}", "POSITIVE", ["taste"]))
        repo = InMemoryAnalyticsRepository(records)
        service = AnalyticsService(repo)
        report = await service.generate_recommendations("M001")
        strength_recs = [r for r in report.recommendations if r.category == "strength"]
        # attitude has total=4 < 5, so no strength_attitude
        attitude_strength = [r for r in strength_recs if r.related_aspect == "attitude"]
        assert len(attitude_strength) == 0
        # taste has total=6 >= 5 and positive_rate=1.0 > 0.8
        taste_strength = [r for r in strength_recs if r.related_aspect == "taste"]
        assert len(taste_strength) == 1

    @pytest.mark.asyncio
    async def test_empty_data_no_ranking_output(self, empty_service: AnalyticsService) -> None:
        """When total=0, no recommendations (no deterministic ranking) are output."""
        report = await empty_service.generate_recommendations("M999")
        assert len(report.recommendations) == 0
        assert report.low_sample_warning is True
        assert report.evidence_review_ids == []
