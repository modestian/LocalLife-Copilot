from __future__ import annotations

from collections import Counter
from typing import Any

import pytest

from app.cli.seed_merchant_data import (
    ANALYSIS_BASE,
    MERCHANT_BASE,
    MERCHANT_DEFS,
    REVIEW_BASE,
    _add_if_missing,
    _generate_reviews_for_merchant,
    _sha256,
    _uuid,
    seed_merchant_data,
)
from app.infrastructure.db.models.operations import Merchant, Review
from app.infrastructure.db.models.sentiment import ReviewAnalysis


class FakeSession:
    def __init__(self, existing: set[tuple[type[Any], Any]] | None = None) -> None:
        self.existing = existing or set()
        self.added: list[object] = []

    async def get(self, model: type[Any], record_id: Any) -> object | None:
        if (model, record_id) in self.existing:
            return object()
        return None

    def add(self, record: object) -> None:
        self.added.append(record)


def test_review_generation_is_deterministic_and_covers_each_trend() -> None:
    generated_by_trend: dict[str, list[dict[str, Any]]] = {}

    for trend in ("stable", "improving", "declining"):
        merchant_index = next(
            index for index, definition in enumerate(MERCHANT_DEFS) if definition["trend"] == trend
        )
        definition = MERCHANT_DEFS[merchant_index]
        first = _generate_reviews_for_merchant(merchant_index, definition)
        second = _generate_reviews_for_merchant(merchant_index, definition)

        assert first == second
        assert len(first) == 20
        assert all(review["text"] and review["aspects"] for review in first)
        generated_by_trend[trend] = first

    assert Counter(review["sentiment"] for review in generated_by_trend["stable"]) == {
        "POSITIVE": 12,
        "NEUTRAL": 4,
        "NEGATIVE": 4,
    }
    assert Counter(review["sentiment"] for review in generated_by_trend["improving"]) == {
        "POSITIVE": 11,
        "NEUTRAL": 4,
        "NEGATIVE": 5,
    }
    assert Counter(review["sentiment"] for review in generated_by_trend["declining"]) == {
        "POSITIVE": 5,
        "NEUTRAL": 4,
        "NEGATIVE": 11,
    }


@pytest.mark.asyncio
async def test_add_if_missing_validates_id_and_is_idempotent() -> None:
    session = FakeSession()
    record = Merchant(id=_uuid(MERCHANT_BASE, 99), name="test", normalized_name="test")

    assert await _add_if_missing(session, record) is True
    assert session.added == [record]

    existing_session = FakeSession({(Merchant, record.id)})
    assert await _add_if_missing(existing_session, record) is False
    assert existing_session.added == []

    with pytest.raises(ValueError, match="must expose an id"):
        await _add_if_missing(session, object())


@pytest.mark.asyncio
async def test_seed_merchant_data_creates_complete_deterministic_dataset() -> None:
    session = FakeSession()
    merchant_total = len(MERCHANT_DEFS)
    review_total = merchant_total * 20

    summary = await seed_merchant_data(session)

    assert summary == {
        "merchants": merchant_total,
        "reviews": review_total,
        "analyses": review_total,
    }
    assert Counter(type(record) for record in session.added) == {
        Merchant: merchant_total,
        Review: review_total,
        ReviewAnalysis: review_total,
    }

    reviews = [record for record in session.added if isinstance(record, Review)]
    analyses = [record for record in session.added if isinstance(record, ReviewAnalysis)]
    assert reviews[0].id == _uuid(REVIEW_BASE, 0)
    assert reviews[-1].id == _uuid(REVIEW_BASE, review_total - 1)
    assert analyses[0].id == _uuid(ANALYSIS_BASE, 0)
    assert analyses[-1].id == _uuid(ANALYSIS_BASE, review_total - 1)
    assert reviews[0].content_hash == _sha256(reviews[0].content)


@pytest.mark.asyncio
async def test_seed_merchant_data_keeps_existing_first_merchants() -> None:
    existing = {
        (Merchant, _uuid(MERCHANT_BASE, 0)),
        (Merchant, _uuid(MERCHANT_BASE, 1)),
    }
    session = FakeSession(existing)
    merchant_total = len(MERCHANT_DEFS)
    review_total = merchant_total * 20

    summary = await seed_merchant_data(session)

    assert summary == {
        "merchants": merchant_total,
        "reviews": review_total,
        "analyses": review_total,
    }
    merchants = [record for record in session.added if isinstance(record, Merchant)]
    assert len(merchants) == merchant_total - 2
