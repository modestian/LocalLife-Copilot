from unittest.mock import AsyncMock, MagicMock

import numpy as np
from fastapi.testclient import TestClient

from app import init_runtime
from app.agents.memory import ConversationMemoryService
from app.agents.runtime import ChatAgentRuntime
from app.agents.tools import ToolExecutor, ToolRegistry
from app.application.auth import AuthService
from app.application.authorization import AuthorizationService
from app.application.model_routing import ModelRouter
from app.core.config import Settings
from app.infrastructure.cache.conversations import RedisConversationMemory
from app.infrastructure.db.repositories.conversations import SQLAlchemyConversationRepository
from app.infrastructure.db.repositories.knowledge import SQLAlchemyKnowledgeRepository
from app.infrastructure.db.repositories.tasks import SQLAlchemyTaskRepository
from app.main import create_app
from app.model_gateway import app as model_gateway_app
from app.worker import ping

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None


def _stub_langchain_adapter_init(self, **kw: object) -> None:
    """Stub __init__ for LangChainRAGAdapter that sets required attributes."""
    self._api_key = kw.get("api_key", "")
    self._api_base = kw.get("api_base", "")
    self._model_name = kw.get("model", "")
    self._temperature = kw.get("temperature", 0.3)
    self._max_tokens = kw.get("max_tokens", 2048)
    self._timeout = kw.get("timeout", 60.0)


def test_model_gateway_liveness() -> None:
    with TestClient(model_gateway_app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_model_gateway_returns_deterministic_dimensioned_embeddings(monkeypatch) -> None:
    dim = Settings().embedding_dimension
    spec = SentenceTransformer if SentenceTransformer is not None else None
    mock_st = MagicMock(spec=spec)
    mock_st.encode.return_value = np.zeros((2, dim))
    monkeypatch.setattr("app.model_gateway._get_embedding_model", lambda: mock_st)

    with TestClient(model_gateway_app) as client:
        response = client.post(
            "/v1/embeddings",
            json={"model": "local-deterministic-v1", "input": ["安静", "安静"]},
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert [item["index"] for item in data] == [0, 1]
    assert len(data[0]["embedding"]) == Settings().embedding_dimension
    assert data[0]["embedding"] == data[1]["embedding"] == [0.0] * dim


def test_model_gateway_returns_classifier_scores_as_mapping(monkeypatch) -> None:
    pipeline = MagicMock(
        return_value=[
            {"label": "NEGATIVE", "score": 0.1},
            {"label": "NEUTRAL", "score": 0.2},
            {"label": "POSITIVE", "score": 0.7},
        ]
    )
    monkeypatch.setattr("app.model_gateway._get_classifier", lambda: pipeline)

    with TestClient(model_gateway_app) as client:
        response = client.post(
            "/v1/classify",
            json={"model": "local-bert-classifier", "input": "推荐一家川菜馆"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "model": "local-bert-classifier",
        "predicted_label": "POSITIVE",
        "scores": {"NEGATIVE": 0.1, "NEUTRAL": 0.2, "POSITIVE": 0.7},
    }


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
    client.indices.update_aliases.assert_called_once()
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
    # langchain-openai is only installed inside Docker — provide a stub for local tests
    monkeypatch.setattr(
        "app.agents.langchain_rag._build_chain",
        lambda *a, **kw: MagicMock(),
    )
    monkeypatch.setattr(
        "app.agents.langchain_rag.LangChainRAGAdapter.__init__",
        _stub_langchain_adapter_init,
    )

    app = create_app(settings=Settings())
    with TestClient(app):
        assert isinstance(app.state.auth_service, AuthService)
        assert isinstance(app.state.authorization_service, AuthorizationService)
        assert isinstance(app.state.knowledge_repository, SQLAlchemyKnowledgeRepository)
        assert isinstance(app.state.task_repository, SQLAlchemyTaskRepository)
        assert isinstance(app.state.conversation_repository, SQLAlchemyConversationRepository)
        assert isinstance(app.state.conversation_memory, RedisConversationMemory)
        assert isinstance(app.state.agent_memory, ConversationMemoryService)
        assert isinstance(app.state.tool_registry, ToolRegistry)
        assert isinstance(app.state.tool_executor, ToolExecutor)
        assert isinstance(app.state.model_router, ModelRouter)
        assert app.state.tool_registry.get("knowledge.search") is not None
        assert isinstance(app.state.agent_runtime, ChatAgentRuntime)

    engine.dispose.assert_awaited_once()
    redis_client.aclose.assert_awaited_once()
    opensearch_client.close.assert_called_once()


def test_st102_runtime_routes_are_exposed() -> None:
    app = create_app(readiness_checks={}, settings=Settings())
    # FastAPI 0.116 stores included routers as _IncludedRouter objects that
    # lack ``.path`` / ``.methods`` attributes until the OpenAPI schema is
    # generated.  Use the schema to obtain fully-resolved path/method pairs.
    schema = app.openapi()
    operations = {
        (path, method.upper())
        for path, methods in schema.get("paths", {}).items()
        for method in methods
    }

    expected = {
        ("/api/v1/knowledge-bases", "POST"),
        ("/api/v1/knowledge-bases", "GET"),
        ("/api/v1/knowledge-bases/{knowledge_base_id}", "PATCH"),
        ("/api/v1/knowledge-bases/{knowledge_base_id}", "DELETE"),
        ("/api/v1/knowledge-bases/{knowledge_base_id}/documents", "GET"),
        ("/api/v1/knowledge-bases/{knowledge_base_id}/documents:upload", "POST"),
        ("/api/v1/documents/{document_id}/rollback", "POST"),
        ("/api/v1/documents/{document_id}/reindex", "POST"),
        ("/api/v1/tasks/{task_id}", "GET"),
        ("/api/v1/tasks/{task_id}/cancel", "POST"),
        ("/api/v1/tasks/{task_id}/retry", "POST"),
        ("/api/v1/conversations", "POST"),
        ("/api/v1/conversations/{conversation_id}/messages", "GET"),
        ("/api/v1/conversations/{conversation_id}/truncate", "POST"),
    }

    assert expected <= operations
