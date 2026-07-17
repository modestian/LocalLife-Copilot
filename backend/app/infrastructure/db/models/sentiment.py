"""Sentiment analysis result persistence models."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import uuid7
from app.infrastructure.db.base import Base, UUIDBinary
from app.infrastructure.db.models.identity import (
    DATETIME_6,
    MYSQL_TABLE_OPTIONS,
    TimestampMixin,
    VersionMixin,
)


class ReviewAnalysis(TimestampMixin, VersionMixin, Base):
    """持久化存储每条点评的情感分析结果。

    aspect_labels 和 negative_reasons 以 JSON 数组形式存储，
    与 SentimentResult Pydantic 模型结构直接对应。
    """

    __tablename__ = "review_analyses"
    __table_args__ = (
        CheckConstraint(
            "sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE')",
            name="sentiment",
        ),
        Index("ix_review_analyses_merchant_sentiment", "merchant_id", "sentiment"),
        Index("ix_review_analyses_review_date", "review_date"),
        Index("ix_review_analyses_sentiment_date", "sentiment", "review_date"),
        MYSQL_TABLE_OPTIONS,
    )

    id: Mapped[UUID] = mapped_column(UUIDBinary(), primary_key=True, default=uuid7)
    merchant_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    review_text: Mapped[str] = mapped_column(Text, nullable=False)
    sentiment: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(mysql.FLOAT(), nullable=False)
    model_version: Mapped[str] = mapped_column(String(128), nullable=False)
    aspect_labels: Mapped[str] = mapped_column(
        mysql.JSON(), nullable=False, default="[]", server_default="('[]')"
    )
    negative_reasons: Mapped[str] = mapped_column(
        mysql.JSON(), nullable=False, default="[]", server_default="('[]')"
    )
    review_date: Mapped[datetime | None] = mapped_column(DATETIME_6, nullable=True)
