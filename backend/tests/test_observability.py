"""Acceptance tests for TK-103-03 logs, metrics and read-only audit queries."""

import json
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_current_principal
from app.api.observability import audit_router, get_audit_service, metrics_router
from app.application.audit import AuditFilter, AuditQueryService, AuditRecord
from app.application.authorization import AuthorizationPrincipal, RoleInfo
from app.core.api import install_api_contract
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.observability import (
    JsonLogFormatter,
    MetricsRegistry,
    bind_log_context,
    redact_sensitive_data,
    reset_log_context,
)


class InMemoryAuditRepository:
    def __init__(self, rows: list[AuditRecord]) -> None:
        self.rows = sorted(rows, key=lambda row: (row.created_at, row.id), reverse=True)
        self.last_filters: AuditFilter | None = None

    async def query(
        self,
        filters: AuditFilter,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[AuditRecord]:
        self.last_filters = filters
        rows = [
            row
            for row in self.rows
            if (filters.actor_id is None or row.actor_id == filters.actor_id)
            and (filters.module is None or row.resource_type == filters.module)
            and (filters.start_time is None or row.created_at >= filters.start_time)
            and (filters.end_time is None or row.created_at <= filters.end_time)
            and (filters.result is None or row.result == filters.result)
            and (cursor is None or (row.created_at, row.id) < cursor)
        ]
        return rows[:limit]


def _audit_row(
    *,
    actor_id: UUID,
    module: str,
    result: str,
    created_at: datetime,
    summary: dict[str, object] | None = None,
) -> AuditRecord:
    return AuditRecord(
        id=uuid7(),
        actor_id=actor_id,
        action="TEST_ACTION",
        resource_type=module,
        resource_id=None,
        request_id=f"request-{uuid7()}",
        ip_address=b"\x7f\x00\x00\x01",
        result=result,
        before_summary=None,
        after_summary=summary,
        created_at=created_at,
    )


def _principal(*, admin: bool = True) -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="audit-admin",
        display_name="Audit admin",
        email=None,
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "Platform admin"),) if admin else (),
        permissions=(),
        resource_grants=(),
    )


def _audit_client(
    service: AuditQueryService, *, principal: AuthorizationPrincipal | None = None
) -> TestClient:
    app = FastAPI()
    settings = Settings()
    app.state.settings = settings
    app.state.metrics_registry = MetricsRegistry()
    install_api_contract(app, settings)
    app.include_router(audit_router, prefix=settings.api_v1_prefix)
    app.include_router(metrics_router)
    app.dependency_overrides[get_audit_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: principal or _principal()
    return TestClient(app)


def test_json_log_contains_required_context_and_redacts_secrets() -> None:
    formatter = JsonLogFormatter()
    tokens = bind_log_context(
        request_id="req-123", user_id=str(uuid7()), conversation_id=str(uuid7())
    )
    try:
        record = logging.LogRecord(
            "app.test",
            logging.WARNING,
            __file__,
            1,
            "request failed password=hunter2 Authorization=Bearer.secret",
            (),
            None,
        )
        record.latency_ms = 12.5
        record.details = {"api_key": "sk-not-visible", "safe": "value"}
        payload = json.loads(formatter.format(record))
    finally:
        reset_log_context(tokens)

    assert payload["level"] == "WARNING"
    assert payload["request_id"] == "req-123"
    assert payload["user_id"] is not None
    assert payload["conversation_id"] is not None
    assert payload["latency_ms"] == 12.5
    assert "hunter2" not in payload["message"]
    assert "Bearer.secret" not in payload["message"]
    assert payload["details"] == {"api_key": "[REDACTED]", "safe": "value"}


def test_recursive_redaction_does_not_mutate_source() -> None:
    source = {"nested": {"refresh_token": "secret-token"}, "items": ["Bearer abc.def"]}
    redacted = redact_sensitive_data(source)

    assert redacted == {
        "nested": {"refresh_token": "[REDACTED]"},
        "items": ["Bearer [REDACTED]"],
    }
    assert source["nested"]["refresh_token"] == "secret-token"  # type: ignore[index]


def test_prometheus_registry_exports_request_model_latency_error_and_tokens() -> None:
    registry = MetricsRegistry()
    registry.observe_request("GET", "/api/v1/audit-logs", 200, 25)
    registry.observe_request("GET", "/api/v1/audit-logs", 500, 125)
    registry.observe_model_call(
        model="local-model",
        result="FAILED",
        latency_ms=250,
        prompt_tokens=12,
        completion_tokens=4,
    )

    output = registry.render_prometheus()

    assert 'status="200"} 1' in output
    assert 'status="500"} 1' in output
    assert "local_life_http_request_duration_seconds_bucket" in output
    assert 'local_life_model_calls_total{model="local-model",result="FAILED"} 1' in output
    assert 'type="prompt"} 12' in output
    assert 'type="completion"} 4' in output


@pytest.mark.asyncio
async def test_audit_query_filters_and_uses_opaque_cursor() -> None:
    actor = uuid7()
    now = datetime(2026, 7, 21, 10, 0)
    rows = [
        _audit_row(
            actor_id=actor,
            module="CONTENT_SAFETY",
            result="BLOCKED",
            created_at=now - timedelta(minutes=index),
        )
        for index in range(3)
    ]
    rows.append(
        _audit_row(
            actor_id=uuid7(),
            module="MODEL",
            result="SUCCEEDED",
            created_at=now,
        )
    )
    repo = InMemoryAuditRepository(rows)
    service = AuditQueryService(repo)

    first = await service.query(
        AuditFilter(actor_id=actor, module="content_safety", result="blocked"), page_size=2
    )
    second = await service.query(
        AuditFilter(actor_id=actor, module="content_safety", result="blocked"),
        page_size=2,
        cursor=first.next_cursor,
    )

    assert len(first.items) == 2
    assert first.next_cursor is not None
    assert len(second.items) == 1
    assert second.next_cursor is None
    assert repo.last_filters is not None
    assert repo.last_filters.module == "CONTENT_SAFETY"
    assert repo.last_filters.result == "BLOCKED"


@pytest.mark.asyncio
async def test_audit_query_normalizes_aware_times_and_rejects_invalid_range() -> None:
    service = AuditQueryService(InMemoryAuditRepository([]))
    aware = datetime(2026, 7, 21, 10, 0, tzinfo=UTC)
    await service.query(AuditFilter(start_time=aware, end_time=aware + timedelta(hours=1)))

    with pytest.raises(ValueError, match="start_time"):
        await service.query(AuditFilter(start_time=aware, end_time=aware - timedelta(seconds=1)))
    with pytest.raises(ValueError, match="cursor"):
        await service.query(AuditFilter(), cursor="not-a-valid-cursor")


def test_admin_audit_api_filters_and_redacts_returned_summaries() -> None:
    actor = uuid7()
    row = _audit_row(
        actor_id=actor,
        module="CONTENT_SAFETY",
        result="BLOCKED",
        created_at=datetime(2026, 7, 21, 10, 0),
        summary={"token": "must-not-leak", "matched": 1},
    )
    repo = InMemoryAuditRepository([row])
    with _audit_client(AuditQueryService(repo)) as client:
        response = client.get(
            "/api/v1/audit-logs",
            params={"user_id": str(actor), "module": "content_safety", "result": "BLOCKED"},
        )

    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["actor_id"] == str(actor)
    assert item["module"] == "CONTENT_SAFETY"
    assert item["after_summary"] == {"token": "[REDACTED]", "matched": 1}
    assert repo.last_filters is not None and repo.last_filters.actor_id == actor


def test_non_admin_cannot_query_audits_and_no_mutation_route_exists() -> None:
    service = AuditQueryService(InMemoryAuditRepository([]))
    with _audit_client(service, principal=_principal(admin=False)) as client:
        denied = client.get("/api/v1/audit-logs")
        patched = client.patch("/api/v1/audit-logs", json={})
        deleted = client.delete("/api/v1/audit-logs")

    assert denied.status_code == 403
    assert patched.status_code == 405
    assert deleted.status_code == 405


def test_metrics_endpoint_uses_prometheus_content_type() -> None:
    service = AuditQueryService(InMemoryAuditRepository([]))
    with _audit_client(service) as client:
        client.get("/api/v1/audit-logs")
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    assert "local_life_http_requests_total" in response.text
    assert 'route="/api/v1/audit-logs"' in response.text


def test_metrics_endpoint_rejects_untrusted_client_identity_in_production() -> None:
    app = FastAPI()
    settings = Settings(
        app_environment="production",
        jwt_secret_key="production-test-secret-key-with-at-least-32-bytes",
    )
    app.state.settings = settings
    app.state.metrics_registry = MetricsRegistry()
    install_api_contract(app, settings)
    app.include_router(metrics_router)

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
