from typing import Annotated, Any
from uuid import UUID

from fastapi import FastAPI, Query, Request
from fastapi.testclient import TestClient

from app.core.api import success_response
from app.core.config import Settings
from app.core.errors import AppError
from app.main import create_app


def build_contract_app(settings: Settings | None = None) -> FastAPI:
    app = create_app(readiness_checks={}, settings=settings or Settings())

    @app.get("/api/v1/example")
    async def example(request: Request) -> dict[str, Any]:
        return success_response(request, {"value": 42})

    @app.get("/api/v1/validated")
    async def validated(
        request: Request, limit: Annotated[int, Query(ge=1, le=100)]
    ) -> dict[str, Any]:
        return success_response(request, {"limit": limit})

    @app.get("/api/v1/conflict")
    async def conflict() -> None:
        raise AppError(
            409,
            "VERSION_CONFLICT",
            "资源版本冲突",
            [{"field": "version", "reason": "stale"}],
        )

    @app.get("/api/v1/unexpected")
    async def unexpected() -> None:
        raise RuntimeError("database password must not leak")

    return app


def test_fastapi_entry_uses_settings_metadata() -> None:
    settings = Settings(app_name="Contract API", app_version="2.3.4")
    app = build_contract_app(settings)

    assert app.title == "Contract API"
    assert app.version == "2.3.4"
    assert app.state.settings is settings


def test_success_response_uses_standard_envelope_and_generated_uuid7() -> None:
    with TestClient(build_contract_app()) as client:
        response = client.get("/api/v1/example")

    payload = response.json()
    request_id = UUID(payload["request_id"])
    assert response.status_code == 200
    assert request_id.version == 7
    assert response.headers["X-Request-ID"] == payload["request_id"]
    assert payload == {
        "code": "OK",
        "message": "success",
        "data": {"value": 42},
        "request_id": payload["request_id"],
    }


def test_caller_request_id_is_preserved_in_header_and_body() -> None:
    with TestClient(build_contract_app()) as client:
        response = client.get("/api/v1/example", headers={"X-Request-ID": "frontend-request-123"})

    assert response.headers["X-Request-ID"] == "frontend-request-123"
    assert response.json()["request_id"] == "frontend-request-123"


def test_invalid_request_id_is_replaced() -> None:
    settings = Settings(request_id_max_length=16)
    with TestClient(build_contract_app(settings)) as client:
        response = client.get("/api/v1/example", headers={"X-Request-ID": "x" * 17})

    generated = response.json()["request_id"]
    assert generated != "x" * 17
    assert UUID(generated).version == 7


def test_application_error_uses_safe_error_envelope() -> None:
    with TestClient(build_contract_app()) as client:
        response = client.get("/api/v1/conflict", headers={"X-Request-ID": "conflict-request"})

    assert response.status_code == 409
    assert response.json() == {
        "code": "VERSION_CONFLICT",
        "message": "资源版本冲突",
        "details": [{"field": "version", "reason": "stale"}],
        "request_id": "conflict-request",
    }


def test_validation_error_uses_standard_error_envelope() -> None:
    with TestClient(build_contract_app()) as client:
        response = client.get("/api/v1/validated", params={"limit": 0})

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert response.json()["details"] == [{"field": "query.limit", "reason": "greater_than_equal"}]


def test_unknown_route_uses_standard_404_envelope() -> None:
    with TestClient(build_contract_app()) as client:
        response = client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_unexpected_error_is_hidden_and_keeps_request_id() -> None:
    with TestClient(build_contract_app(), raise_server_exceptions=False) as client:
        response = client.get("/api/v1/unexpected", headers={"X-Request-ID": "failure-request"})

    assert response.status_code == 500
    assert "password" not in response.text
    assert response.headers["X-Request-ID"] == "failure-request"
    assert response.json() == {
        "code": "INTERNAL_ERROR",
        "message": "服务内部错误",
        "details": [],
        "request_id": "failure-request",
    }
