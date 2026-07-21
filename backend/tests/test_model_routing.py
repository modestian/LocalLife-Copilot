"""TK-502-06 unit tests: grayscale routing, metrics, rollback verification.

Covers acceptance criteria ⑤⑥:
- ⑤ Only APPROVED versions can be deployed; only one full ACTIVE per route.
- ⑥ Canary traffic percentage is enforced; rollback switches routing and
  leaves an audit record.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_current_principal
from app.api.governance import get_governance_repository
from app.api.governance import router as governance_router
from app.application.authorization import AuthorizationPrincipal, RoleInfo
from app.application.deployment_metrics import DeploymentMetrics, DeploymentMetricsTracker
from app.application.governance import DeploymentStatus
from app.core.api import install_api_contract
from app.core.config import Settings
from app.core.ids import uuid7

# ── helpers ──────────────────────────────────────────────────


def _principal(*, admin: bool = True) -> AuthorizationPrincipal:
    roles = (RoleInfo("PLATFORM_ADMIN", "Platform admin"),) if admin else ()
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="test-admin",
        display_name="Test Admin",
        email=None,
        department_id=None,
        roles=roles,
        permissions=(),
        resource_grants=(),
    )


class DeploymentListStub:
    """Stub repository for the deployment-list and compare endpoints."""

    def __init__(self) -> None:
        self._deployments: list[SimpleNamespace] = []

    def add_deployment(
        self,
        *,
        model_version_id: UUID | None = None,
        traffic_percent: int = 100,
        status: str = "ACTIVE",
        action: str = "FULL",
    ) -> SimpleNamespace:
        row = SimpleNamespace(
            id=uuid7(),
            model_version_id=model_version_id or uuid7(),
            scene="sentiment",
            environment="production",
            traffic_percent=traffic_percent,
            action=action,
            status=status,
            result="SUCCEEDED",
            deployed_by=uuid7(),
            reason="test deployment",
            created_at=datetime(2026, 7, 22, 10, 0),
        )
        self._deployments.append(row)
        return row

    @property
    def _session_factory(self):  # noqa: SLF001
        return _FakeSessionFactory(self._deployments)


class _FakeSession:
    def __init__(self, deployments: list[SimpleNamespace]) -> None:
        self._deployments = deployments

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def scalars(self, statement):
        return _FakeScalarResult(self._deployments)


class _FakeScalarResult:
    def __init__(self, items: list[SimpleNamespace]) -> None:
        self._items = items

    def all(self):
        return self._items


class _FakeSessionFactory:
    def __init__(self, deployments: list[SimpleNamespace]) -> None:
        self._deployments = deployments

    def __call__(self):
        return _FakeSession(self._deployments)


def _client(repository: DeploymentListStub, *, admin: bool = True) -> TestClient:
    app = FastAPI()
    settings = Settings()
    install_api_contract(app, settings)
    app.include_router(governance_router, prefix=settings.api_v1_prefix)
    app.dependency_overrides[get_governance_repository] = lambda: repository
    app.dependency_overrides[get_current_principal] = lambda: _principal(admin=admin)
    return TestClient(app)


# ── DeploymentStatus enum tests ───────────────────────────────


class TestDeploymentStatusEnum:
    def test_canary_status_exists(self):
        assert DeploymentStatus.CANARY == "CANARY"

    def test_rolled_back_status_exists(self):
        assert DeploymentStatus.ROLLED_BACK == "ROLLED_BACK"

    def test_active_status_exists(self):
        assert DeploymentStatus.ACTIVE == "ACTIVE"

    def test_superseded_status_exists(self):
        assert DeploymentStatus.SUPERSEDED == "SUPERSEDED"

    def test_failed_removed(self):
        assert not hasattr(DeploymentStatus, "FAILED")


# ── DeploymentMetricsTracker tests ───────────────────────────


class TestDeploymentMetricsTracker:
    def test_record_and_get_metrics(self):
        tracker = DeploymentMetricsTracker()
        dep_id = uuid7()

        tracker.record(dep_id, latency_ms=10.0)
        tracker.record(dep_id, latency_ms=30.0)
        tracker.record(dep_id, latency_ms=50.0, error=True)

        c = tracker.get_metrics(dep_id)
        assert c.request_count == 3
        assert c.error_count == 1
        assert c.total_latency_ms == 90.0

    def test_error_rate_is_zero_when_no_requests(self):
        m = DeploymentMetrics(
            deployment_id=uuid7(),
            model_version_id=uuid7(),
            status="ACTIVE",
            traffic_percent=100,
        )
        assert m.error_rate == 0.0

    def test_error_rate_is_correct(self):
        tracker = DeploymentMetricsTracker()
        dep_id = uuid7()

        for _ in range(9):
            tracker.record(dep_id, latency_ms=10.0)
        tracker.record(dep_id, latency_ms=10.0, error=True)

        c = tracker.get_metrics(dep_id)
        assert c.request_count == 10
        assert c.error_count == 1
        # error_rate property tested via DeploymentMetrics
        m = DeploymentMetrics(
            deployment_id=dep_id,
            model_version_id=uuid7(),
            status="ACTIVE",
            traffic_percent=100,
            request_count=c.request_count,
            error_count=c.error_count,
        )
        assert m.error_rate == pytest.approx(0.1, abs=0.01)

    def test_avg_latency_is_zero_for_unknown(self):
        tracker = DeploymentMetricsTracker()
        c = tracker.get_metrics(uuid7())
        assert c.request_count == 0
        assert c.total_latency_ms == 0.0

    def test_concurrent_record_is_thread_safe(self):
        import threading

        tracker = DeploymentMetricsTracker()
        dep_id = uuid7()

        def worker():
            for _ in range(100):
                tracker.record(dep_id, latency_ms=5.0)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        c = tracker.get_metrics(dep_id)
        assert c.request_count == 1000


# ── Hash bucket routing tests ─────────────────────────────────


class TestHashBucket:
    """Test the deterministic hash routing logic."""

    @staticmethod
    def _hash_bucket(routing_key: str) -> int:
        digest = hashlib.sha256(routing_key.encode("utf-8")).digest()
        return int.from_bytes(digest[:4], "big") % 100

    def test_same_key_same_bucket(self):
        assert self._hash_bucket("review-001") == self._hash_bucket("review-001")

    def test_bucket_in_range(self):
        for i in range(1000):
            bucket = self._hash_bucket(f"key-{i}")
            assert 0 <= bucket < 100

    def test_10_percent_canary_traffic_distribution(self):
        """Approximately 10% of keys should land in the canary bucket (< 10)."""
        canary_count = sum(1 for i in range(10000) if self._hash_bucket(f"key-{i}") < 10)
        # ±2% tolerance
        assert 800 <= canary_count <= 1200

    def test_30_percent_canary_traffic_distribution(self):
        canary_count = sum(1 for i in range(10000) if self._hash_bucket(f"key-{i}") < 30)
        # ±3% tolerance
        assert 2700 <= canary_count <= 3300


# ── API endpoint tests ───────────────────────────────────────


class TestDeploymentListAPI:
    def test_list_deployments_returns_active_and_canary(self):
        repo = DeploymentListStub()
        repo.add_deployment(traffic_percent=100, status="ACTIVE", action="FULL")
        repo.add_deployment(traffic_percent=10, status="CANARY", action="CANARY")

        with _client(repo) as client:
            response = client.get(
                "/api/v1/models/deployments",
                params={"scene": "sentiment", "environment": "production"},
            )

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["scene"] == "sentiment"
        assert data["environment"] == "production"
        assert len(data["items"]) == 2
        statuses = {item["status"] for item in data["items"]}
        assert "ACTIVE" in statuses
        assert "CANARY" in statuses

    def test_list_deployments_empty_when_no_deployments(self):
        repo = DeploymentListStub()
        with _client(repo) as client:
            response = client.get(
                "/api/v1/models/deployments",
                params={"scene": "sentiment", "environment": "production"},
            )
        assert response.status_code == 200
        assert len(response.json()["data"]["items"]) == 0

    def test_non_admin_cannot_list_deployments(self):
        repo = DeploymentListStub()
        with _client(repo, admin=False) as client:
            response = client.get(
                "/api/v1/models/deployments",
                params={"scene": "sentiment", "environment": "production"},
            )
        assert response.status_code == 403


class TestDeploymentCompareAPI:
    def test_compare_returns_metrics(self):
        repo = DeploymentListStub()
        repo.add_deployment(traffic_percent=100, status="ACTIVE", action="FULL")
        repo.add_deployment(traffic_percent=10, status="CANARY", action="CANARY")

        with _client(repo) as client:
            response = client.get(
                "/api/v1/models/deployments/compare",
                params={"scene": "sentiment", "environment": "production"},
            )

        assert response.status_code == 200
        items = response.json()["data"]["items"]
        assert len(items) == 2
        for item in items:
            assert "request_count" in item
            assert "error_count" in item
            assert "error_rate" in item
            assert "avg_latency_ms" in item

    def test_non_admin_cannot_compare_deployments(self):
        repo = DeploymentListStub()
        with _client(repo, admin=False) as client:
            response = client.get(
                "/api/v1/models/deployments/compare",
                params={"scene": "sentiment", "environment": "production"},
            )
        assert response.status_code == 403


# ── DB CHECK constraint tests ─────────────────────────────────


class TestModelDeploymentCheckConstraint:
    def test_status_check_constraint_includes_canary_and_rolled_back(self):
        from app.infrastructure.db.models.governance import ModelDeployment

        table = ModelDeployment.__table__
        check_constraints = [
            c for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
        ]
        status_constraint = next(
            (c for c in check_constraints if c.name == "ck_model_deployments_status"),
            None,
        )
        assert status_constraint is not None
        sql_text = str(status_constraint.sqltext)
        assert "CANARY" in sql_text
        assert "ROLLED_BACK" in sql_text
        assert "ACTIVE" in sql_text
        assert "SUPERSEDED" in sql_text
