"""Grayscale model routing service.

§9.4 — 先 10% 灰度，监控错误率、延迟和用户反馈；超过阈值自动或人工回滚到上一版本。
§9.5 — Model Adapter 接口统一 predict(batch)；配置切换只改变注册版本。

The router reads the current ACTIVE and CANARY deployments from the
governance repository and applies deterministic hash-based traffic
splitting so that the same routing_key always lands on the same model.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.governance import DeploymentStatus
from app.infrastructure.db.models.governance import ModelDeployment


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """The deployment and model version that a single request should use."""

    model_version_id: UUID
    deployment_id: UUID
    traffic_percent: int
    is_canary: bool


class ModelRouter:
    """Resolve the active model deployment for a given scene and environment.

    Routing strategy
    ----------------
    1. Query all ACTIVE + CANARY deployments for the route.
    2. If only an ACTIVE deployment exists → return it (100 % traffic).
    3. If both ACTIVE and CANARY exist → deterministic hash:
       hash(routing_key) % 100 < canary.traffic_percent  →  CANARY
       otherwise                                         →  ACTIVE
    4. No deployments → return None (caller must handle fallback).
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(
        self,
        scene: str,
        environment: str,
        routing_key: str,
    ) -> RoutingDecision | None:
        deployments = await self._query_active(scene, environment)
        if not deployments:
            return None

        active = next((d for d in deployments if d.status == DeploymentStatus.ACTIVE.value), None)
        canary = next((d for d in deployments if d.status == DeploymentStatus.CANARY.value), None)

        if canary is not None and active is not None:
            bucket = _hash_bucket(routing_key)
            if bucket < canary.traffic_percent:
                return _to_decision(canary, is_canary=True)
            return _to_decision(active, is_canary=False)

        # Only one deployment present — could be ACTIVE-only or CANARY-only.
        sole = active or canary
        assert sole is not None
        return _to_decision(sole, is_canary=(canary is not None and active is None))

    async def list_active(self, scene: str, environment: str) -> list[RoutingDecision]:
        """Return all active deployments for the route (ACTIVE + CANARY)."""
        deployments = await self._query_active(scene, environment)
        return [
            _to_decision(d, is_canary=(d.status == DeploymentStatus.CANARY.value))
            for d in deployments
        ]

    async def _query_active(self, scene: str, environment: str) -> list[ModelDeployment]:
        async with self._session_factory() as session:
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
            return list(result.all())


def _to_decision(row: ModelDeployment, *, is_canary: bool) -> RoutingDecision:
    return RoutingDecision(
        model_version_id=row.model_version_id,
        deployment_id=row.id,
        traffic_percent=row.traffic_percent,
        is_canary=is_canary,
    )


def _hash_bucket(routing_key: str) -> int:
    """Map *routing_key* to a deterministic bucket in [0, 99]."""
    digest = hashlib.sha256(routing_key.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 100
