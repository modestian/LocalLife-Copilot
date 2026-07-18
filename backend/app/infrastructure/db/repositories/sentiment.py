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

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
        async with self._session_factory() as session:
            stmt = select(ReviewAnalysis).where(ReviewAnalysis.merchant_id == merchant_id)
            if sentiment:
                stmt = stmt.where(ReviewAnalysis.sentiment == sentiment)
            stmt = stmt.order_by(ReviewAnalysis.created_at.desc()).offset(offset).limit(limit)
            rows = await session.scalars(stmt)
            return list(rows)

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
