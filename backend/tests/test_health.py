from collections.abc import Awaitable, Callable

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


async def healthy() -> None:
    return None


async def unhealthy() -> None:
    raise ConnectionError("dependency unavailable")


def client_with(
    checks: dict[str, Callable[[], Awaitable[None]]],
) -> TestClient:
    settings = Settings(dependency_timeout_seconds=0.1)
    return TestClient(create_app(readiness_checks=checks, settings=settings))


def test_liveness_does_not_require_dependencies() -> None:
    with client_with({"mysql": unhealthy}) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_reports_all_dependencies_up() -> None:
    checks = {
        "mysql": healthy,
        "redis": healthy,
        "opensearch": healthy,
        "model_gateway": healthy,
    }
    with client_with(checks) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "mysql": "up",
            "redis": "up",
            "opensearch": "up",
            "model_gateway": "up",
        },
    }


def test_readiness_returns_503_without_leaking_error_details() -> None:
    with client_with({"mysql": healthy, "redis": unhealthy}) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "checks": {"mysql": "up", "redis": "down"},
    }
