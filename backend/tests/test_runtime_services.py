from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app import init_runtime
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
    client.close.assert_called_once()
