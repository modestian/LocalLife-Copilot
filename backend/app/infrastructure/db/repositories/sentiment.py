"""Sentiment analysis result repository."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
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
