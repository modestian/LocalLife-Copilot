"""Sentiment analysis result repository."""

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.authorization import AuthorizationPrincipal, ResourceType
from app.infrastructure.db.models.sentiment import ReviewAnalysis


@dataclass(frozen=True, slots=True)
class SentimentAnalysisRecord:
    """Lightweight DTO for persisting sentiment results.

    Decouples the infrastructure layer from the analytics module (which
    requires torch). Constructed by the application service before calling
    batch_save().
    """

    sentiment: str
    confidence: float
    model_version: str
    aspect_labels: list[str] = ()
    negative_reasons: list[str] = ()
    review_text: str = ""
    review_date: datetime | None = None


class SQLAlchemySentimentRepository:
    """Async CRUD for ReviewAnalysis persistence."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        principal: AuthorizationPrincipal | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._principal = principal

    def scoped(self, principal: AuthorizationPrincipal) -> "SQLAlchemySentimentRepository":
        """Create a request-scoped repository with mandatory merchant grants."""
        return type(self)(self._session_factory, principal=principal)

    def _authorize_merchant(self, merchant_id: str, action: str = "READ") -> None:
        if self._principal is not None:
            self._principal.require_resource_access(
                ResourceType.MERCHANT,
                UUID(merchant_id),
                action,
            )

    def _authorize_merchants(self, merchant_ids: Sequence[str], action: str = "READ") -> None:
        for merchant_id in merchant_ids:
            self._authorize_merchant(merchant_id, action)

    async def batch_save(
        self,
        records: Sequence[SentimentAnalysisRecord],
        *,
        merchant_id: str | None = None,
    ) -> list[UUID]:
        """Persist a batch of sentiment analysis results in a single transaction.

        Returns:
            List of created ReviewAnalysis primary key UUIDs.
        """
        if not records:
            return []
        if merchant_id is not None:
            self._authorize_merchant(merchant_id, "CREATE")

        ids: list[UUID] = []
        async with self._session_factory() as session, session.begin():
            for record in records:
                entity = ReviewAnalysis(
                    merchant_id=merchant_id,
                    review_text=record.review_text,
                    sentiment=record.sentiment,
                    confidence=record.confidence,
                    model_version=record.model_version,
                    aspect_labels=json.dumps(record.aspect_labels, ensure_ascii=False),
                    negative_reasons=json.dumps(record.negative_reasons, ensure_ascii=False),
                    review_date=record.review_date,
                )
                session.add(entity)
                await session.flush()
                ids.append(entity.id)
        return ids

    async def find_by_merchant(
        self,
        merchant_id: str,
        *,
        sentiment: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReviewAnalysis]:
        """Query analysis results for a merchant, optionally filtered by sentiment."""
        self._authorize_merchant(merchant_id)
        async with self._session_factory() as session:
            stmt = select(ReviewAnalysis).where(ReviewAnalysis.merchant_id == merchant_id)
            if sentiment:
                stmt = stmt.where(ReviewAnalysis.sentiment == sentiment)
            stmt = stmt.order_by(ReviewAnalysis.created_at.desc()).offset(offset).limit(limit)
            rows = await session.scalars(stmt)
            return list(rows)

    async def find_review_by_id(self, review_id: UUID) -> ReviewAnalysis | None:
        """Look up a single review analysis by primary key."""
        async with self._session_factory() as session:
            return await session.get(ReviewAnalysis, review_id)

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------

    _GRANULARITY_FORMATS: dict[str, str] = {
        "day": "%Y-%m-%d",
        "week": "%x-W%v",
        "month": "%Y-%m",
    }

    async def get_sentiment_trend(
        self,
        merchant_id: str,
        *,
        granularity: Literal["day", "week", "month"] = "day",
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return sentiment counts grouped by time bucket.

        Args:
            merchant_id: Target merchant.
            granularity: One of ``day``, ``week``, ``month``.
            start_date: Inclusive lower bound on ``review_date``.
            end_date: **Exclusive** upper bound on ``review_date``.

        Returns:
            List of dicts, each with keys ``period``, ``positive``,
            ``neutral``, ``negative``.
        """
        self._authorize_merchant(merchant_id)
        fmt = self._GRANULARITY_FORMATS.get(granularity, "%Y-%m-%d")

        sql = text(
            f"SELECT DATE_FORMAT(review_date, :fmt) AS period, "
            f"SUM(sentiment = 'POSITIVE') AS positive, "
            f"SUM(sentiment = 'NEUTRAL') AS neutral, "
            f"SUM(sentiment = 'NEGATIVE') AS negative "
            f"FROM review_analyses "
            f"WHERE merchant_id = :merchant_id "
            f"{'AND review_date >= :start_date ' if start_date else ''}"
            f"{'AND review_date < :end_date ' if end_date else ''}"
            f"GROUP BY period ORDER BY period"
        )

        params: dict = {"merchant_id": merchant_id, "fmt": fmt}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        async with self._session_factory() as session:
            result = await session.execute(sql, params)
            return [
                {
                    "period": row[0],
                    "positive": int(row[1] or 0),
                    "neutral": int(row[2] or 0),
                    "negative": int(row[3] or 0),
                }
                for row in result.fetchall()
            ]

    async def get_negative_reason_aggregation(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Aggregate negative-reason counts in Python to avoid MySQL JSON compat issues.

        Returns:
            List of ``{"reason": str, "count": int}`` sorted by count descending.
        """
        self._authorize_merchant(merchant_id)
        async with self._session_factory() as session:
            stmt = select(ReviewAnalysis.negative_reasons).where(
                ReviewAnalysis.merchant_id == merchant_id,
                ReviewAnalysis.sentiment == "NEGATIVE",
            )
            if start_date:
                stmt = stmt.where(ReviewAnalysis.review_date >= start_date)
            if end_date:
                stmt = stmt.where(ReviewAnalysis.review_date < end_date)

            rows = await session.scalars(stmt)

        counter: Counter[str] = Counter()
        for raw in rows:
            try:
                reasons = json.loads(raw) if isinstance(raw, str) else raw
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(reasons, list):
                counter.update(reasons)

        return [{"reason": reason, "count": count} for reason, count in counter.most_common()]

    async def get_aspect_sentiment_stats(
        self,
        merchant_id: str,
        *,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> list[dict]:
        """Return per-aspect sentiment distribution for a merchant.

        For each aspect label found in the merchant's reviews, counts how
        many POSITIVE / NEUTRAL / NEGATIVE reviews mention it.

        Returns:
            List of dicts with keys ``aspect``, ``positive``, ``neutral``,
            ``negative``, ``total``, ``positive_rate`` sorted by
            ``positive_rate`` descending.
        """
        self._authorize_merchant(merchant_id)
        async with self._session_factory() as session:
            stmt = select(ReviewAnalysis.aspect_labels, ReviewAnalysis.sentiment).where(
                ReviewAnalysis.merchant_id == merchant_id
            )
            if start_date:
                stmt = stmt.where(ReviewAnalysis.review_date >= start_date)
            if end_date:
                stmt = stmt.where(ReviewAnalysis.review_date < end_date)

            rows = (await session.execute(stmt)).all()

        # Per-aspect counters: {aspect: {sentiment: count}}
        stats: dict[str, Counter[str]] = {}
        for raw_aspects, sentiment in rows:
            try:
                aspects = json.loads(raw_aspects) if isinstance(raw_aspects, str) else raw_aspects
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(aspects, list):
                continue
            for aspect in aspects:
                if aspect not in stats:
                    stats[aspect] = Counter()
                stats[aspect][sentiment] += 1

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
        """Return per-period positive rate and trend classification.

        Builds on top of :meth:`get_sentiment_trend`, adding:
        - ``positive_rate``: positive / total for each period
        - ``change``: difference vs previous period (None for the first)
        - ``trend``: one of ``improving``, ``declining``, ``stable``
        """
        trend_data = await self.get_sentiment_trend(
            merchant_id,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        )

        result: list[dict] = []
        prev_rate: float | None = None
        threshold = 0.05  # 5% change is significant
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
        """Return per-merchant sentiment summary for comparison.

        Queries multiple merchants in a single SQL pass and returns a
        dict keyed by ``merchant_id``.

        Each value contains:
        - ``positive``, ``neutral``, ``negative``, ``total``
        - ``positive_rate``, ``negative_rate``

        Args:
            merchant_ids: 2-4 merchant IDs to compare.
            start_date: Inclusive lower bound on ``review_date``.
            end_date: Exclusive upper bound on ``review_date``.
        """
        if not merchant_ids:
            return {}
        self._authorize_merchants(merchant_ids)

        placeholders = ", ".join(f":mid{i}" for i in range(len(merchant_ids)))
        sql = text(
            f"SELECT merchant_id, "
            f"SUM(sentiment = 'POSITIVE') AS positive, "
            f"SUM(sentiment = 'NEUTRAL') AS neutral, "
            f"SUM(sentiment = 'NEGATIVE') AS negative "
            f"FROM review_analyses "
            f"WHERE merchant_id IN ({placeholders}) "
            f"{'AND review_date >= :start_date ' if start_date else ''}"
            f"{'AND review_date < :end_date ' if end_date else ''}"
            f"GROUP BY merchant_id"
        )

        params: dict = {f"mid{i}": mid for i, mid in enumerate(merchant_ids)}
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date

        async with self._session_factory() as session:
            result = await session.execute(sql, params)
            rows = result.fetchall()

        stats: dict[str, dict] = {}
        for row in rows:
            mid, positive, neutral, negative = (
                row[0],
                int(row[1] or 0),
                int(row[2] or 0),
                int(row[3] or 0),
            )
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

        # Ensure all requested merchants appear in output (even with 0 reviews)
        for mid in merchant_ids:
            if mid not in stats:
                stats[mid] = {
                    "merchant_id": mid,
                    "positive": 0,
                    "neutral": 0,
                    "negative": 0,
                    "total": 0,
                    "positive_rate": 0.0,
                    "negative_rate": 0.0,
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
    ) -> list[ReviewAnalysis]:
        """Return original reviews with multi-dimensional filtering.

        The ``negative_reason`` filter is applied in Python after the SQL
        query, because the column stores a JSON array.
        """
        self._authorize_merchant(merchant_id)
        async with self._session_factory() as session:
            stmt = select(ReviewAnalysis).where(
                ReviewAnalysis.merchant_id == merchant_id,
            )
            if sentiment:
                stmt = stmt.where(ReviewAnalysis.sentiment == sentiment)
            if start_date:
                stmt = stmt.where(ReviewAnalysis.review_date >= start_date)
            if end_date:
                stmt = stmt.where(ReviewAnalysis.review_date < end_date)

            # Fetch more rows than needed when Python-side filtering is required
            fetch_limit = limit * 5 if negative_reason else limit
            stmt = stmt.order_by(ReviewAnalysis.review_date.desc()).limit(fetch_limit)
            rows = list(await session.scalars(stmt))

        # Python-side negative_reason filter
        if negative_reason:
            filtered: list[ReviewAnalysis] = []
            for row in rows:
                try:
                    reasons = (
                        json.loads(row.negative_reasons)
                        if isinstance(row.negative_reasons, str)
                        else row.negative_reasons
                    )
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(reasons, list) and negative_reason in reasons:
                    filtered.append(row)
                    if len(filtered) >= limit:
                        break
            return filtered

        return rows[offset : offset + limit]
