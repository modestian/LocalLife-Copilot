from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app import init_runtime
from app.application.auth import AuthService
from app.application.authorization import AuthorizationService
from app.core.config import Settings
from app.main import create_app
from app.model_gateway import app as model_gateway_app
from app.worker import ping


def test_model_gateway_liveness() -> None:
    with TestClient(model_gateway_app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_worker_ping_task_contract() -> None:
    assert ping() == "pong"


def test_init_runtime_creates_missing_index(monkeypatch) -> None:
    client = MagicMock()
    client.indices.exists.return_value = False
    monkeypatch.setattr(init_runtime, "OpenSearch", MagicMock(return_value=client))

    init_runtime.main()

    client.indices.create.assert_called_once()
    client.close.assert_called_once()


def test_init_runtime_is_idempotent(monkeypatch) -> None:
    client = MagicMock()
    client.indices.exists.return_value = True
    monkeypatch.setattr(init_runtime, "OpenSearch", MagicMock(return_value=client))

    init_runtime.main()

    client.indices.create.assert_not_called()
    client.indices.put_mapping.assert_called_once()
    client.close.assert_called_once()


def test_api_lifespan_wires_authentication_and_authorization_services(monkeypatch) -> None:
    engine = MagicMock()
    engine.dispose = AsyncMock()
    redis_client = MagicMock()
    redis_client.aclose = AsyncMock()
    opensearch_client = MagicMock()

    monkeypatch.setattr("app.main.create_async_engine", MagicMock(return_value=engine))
    monkeypatch.setattr("app.main.Redis.from_url", MagicMock(return_value=redis_client))
    monkeypatch.setattr("app.main.OpenSearch", MagicMock(return_value=opensearch_client))
    monkeypatch.setattr("app.main.build_readiness_checks", MagicMock(return_value={}))

    app = create_app(settings=Settings())
    with TestClient(app):
        assert isinstance(app.state.auth_service, AuthService)
        assert isinstance(app.state.authorization_service, AuthorizationService)

    engine.dispose.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
    opensearch_client.close.assert_called_once()
