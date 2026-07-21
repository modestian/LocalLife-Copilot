"""In-process runtime metrics for model deployments.

§9.4 — 先 10% 灰度，监控错误率、延迟和用户反馈；超过阈值自动或人工回滚。

The tracker collects per-deployment request counts, error counts and
latency in process memory.  It is **not** a durable store — the data
lives only for the lifetime of the process.  The primary consumer is
the deployment comparison API that helps operators decide whether to
promote a canary or roll it back.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.governance import DeploymentStatus
from app.infrastructure.db.models.governance import ModelDeployment


@dataclass
class DeploymentMetrics:
    """Snapshot of runtime metrics for a single deployment."""

    deployment_id: UUID
    model_version_id: UUID
    status: str
    traffic_percent: int
    request_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0

    @property
    def error_rate(self) -> float:
        """Fraction of requests that resulted in an error (0.0–1.0)."""
        return self.error_count / self.request_count if self.request_count else 0.0


@dataclass
class _Counters:
    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0


class DeploymentMetricsTracker:
    """Thread-safe in-process metrics collector."""

    def __init__(self) -> None:
        self._counters: dict[UUID, _Counters] = {}
        self._lock = threading.Lock()

    def record(self, deployment_id: UUID, latency_ms: float, error: bool = False) -> None:
        """Record a single request outcome."""
        with self._lock:
            c = self._counters.setdefault(deployment_id, _Counters())
            c.request_count += 1
            if error:
                c.error_count += 1
            c.total_latency_ms += latency_ms

    def get_metrics(self, deployment_id: UUID) -> _Counters:
        """Return the raw counters for *deployment_id* (zero-valued if unknown)."""
        with self._lock:
            return self._counters.get(deployment_id, _Counters())

    async def compare(
        self,
        scene: str,
        environment: str,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> list[DeploymentMetrics]:
        """Return metrics for all ACTIVE + CANARY deployments on the route."""
        async with session_factory() as session:
            result = await session.scalars(
                select(ModelDeployment)
                .where(
                    ModelDeployment.scene == scene,
                    ModelDeployment.environment == environment,
                    ModelDeployment.status.in_(
                        [DeploymentStatus.ACTIVE.value, DeploymentStatus.CANARY.value]
                    ),
                )
                .order_by(ModelDeployment.created_at.desc())
            )
            rows = list(result.all())

        metrics: list[DeploymentMetrics] = []
        for row in rows:
            c = self.get_metrics(row.id)
            avg_latency = c.total_latency_ms / c.request_count if c.request_count else 0.0
            metrics.append(
                DeploymentMetrics(
                    deployment_id=row.id,
                    model_version_id=row.model_version_id,
                    status=row.status,
                    traffic_percent=row.traffic_percent,
                    request_count=c.request_count,
                    error_count=c.error_count,
                    avg_latency_ms=round(avg_latency, 2),
                )
            )
        return metrics
