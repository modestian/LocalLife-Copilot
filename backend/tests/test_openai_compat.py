import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

from app.agents.contracts import RetrievalScope
from app.api.dependencies.authorization import get_current_principal
from app.application.authorization import AuthorizationPrincipal
from app.application.conversations import MessageRole, MessageStatus, MessageView, SourceView
from app.core.errors import AppError
from app.main import create_app

USER_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125")
TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b121")
CONVERSATION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b126")
MESSAGE_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b127")
CHUNK_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b128")


def principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=USER_ID,
        username="sdk-user",
        display_name="SDK User",
        email=None,
        department_id=TENANT_ID,
        roles=(),
        permissions=(),
        resource_grants=(),
    )


def assistant_message() -> MessageView:
    return MessageView(
        id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        parent_message_id=None,
        sequence_no=2,
        request_id="assistant:request",
        role=MessageRole.ASSISTANT,
        content="Try the quiet restaurant by the park.",
        status=MessageStatus.COMPLETED,
        model_version_id=None,
        prompt_tokens=12,
        completion_tokens=8,
        latency_ms=25,
        error_code=None,
        created_at=datetime(2026, 7, 21, 8, 0, tzinfo=UTC),
        sources=(
            SourceView(
                chunk_id=CHUNK_ID,
                rank_no=1,
                source_location_snapshot="reviews/merchant-a/1",
                content_snapshot="Quiet tables are available by the window.",
                score=0.91,
                raw_score=None,
            ),
        ),
    )


def build_client():
    app = create_app(readiness_checks={})
    app.dependency_overrides[get_current_principal] = principal
    app.state.conversation_repository = AsyncMock()
    app.state.conversation_memory = AsyncMock()
    app.state.agent_runtime = AsyncMock()
    app.state.agent_runtime.run.return_value = SimpleNamespace(message=assistant_message())
    return app, TestClient(app)


def payload() -> dict[str, object]:
    return {
        "model": "local-life-assistant",
        "messages": [{"role": "user", "content": "Where should we eat?"}],
        "conversation_id": str(CONVERSATION_ID),
        "stream": False,
    }


def test_non_streaming_response_matches_openai_chat_completion_shape() -> None:
    app, client = build_client()
    with client:
        response = client.post("/v1/chat/completions", json=payload())

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == f"chatcmpl-{MESSAGE_ID}"
    assert body["object"] == "chat.completion"
    assert body["model"] == "local-life-assistant"
    assert body["choices"] == [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "Try the quiet restaurant by the park.",
            },
            "finish_reason": "stop",
        }
    ]
    assert body["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    assert body["conversation_id"] == str(CONVERSATION_ID)
    assert body["message_id"] == str(MESSAGE_ID)
    assert body["sources"][0] == {
        "chunk_id": str(CHUNK_ID),
        "source_location": "reviews/merchant-a/1",
        "source_url": f"/app/chunks/{CHUNK_ID}",
        "content": "Quiet tables are available by the window.",
        "score": 0.91,
    }
    scope = app.state.agent_runtime.run.await_args.kwargs["retrieval_scope"]
    assert scope.tenant_id == str(TENANT_ID)
    assert scope.knowledge_base_ids == frozenset()


def test_chat_uses_shared_public_knowledge_for_user_without_department() -> None:
    app, client = build_client()
    app.dependency_overrides[get_current_principal] = lambda: AuthorizationPrincipal(
        user_id=USER_ID,
        username="personal-user",
        display_name="Personal User",
        email=None,
        department_id=None,
        roles=(),
        permissions=(),
        resource_grants=(),
    )
    public_kb_id = UUID("70200000-0000-4000-8000-000000000010")
    app.state.shared_chat_knowledge_scope = AsyncMock()
    app.state.shared_chat_knowledge_scope.resolve.return_value = RetrievalScope(
        str(TENANT_ID),
        frozenset({str(public_kb_id)}),
        frozenset({f"KNOWLEDGE_BASE:{public_kb_id}"}),
    )

    with client:
        response = client.post(
            "/v1/chat/completions",
            json={**payload(), "knowledge_base_ids": [str(public_kb_id)]},
        )

    assert response.status_code == 200
    app.state.shared_chat_knowledge_scope.resolve.assert_awaited_once_with([public_kb_id])
    scope = app.state.agent_runtime.run.await_args.kwargs["retrieval_scope"]
    assert scope.tenant_id == str(TENANT_ID)
    assert scope.knowledge_base_ids == frozenset({str(public_kb_id)})


def test_validation_errors_use_openai_error_object() -> None:
    _app, client = build_client()
    with client:
        invalid = client.post(
            "/v1/chat/completions",
            json={"model": "local-life-assistant", "messages": []},
        )

    assert invalid.status_code == 422
    assert invalid.json()["error"] == {
        "message": "请求字段校验失败",
        "type": "invalid_request_error",
        "param": "messages",
        "code": "validation_error",
    }


def test_streaming_response_emits_ordered_chunks_sources_and_done() -> None:
    _app, client = build_client()
    with client:
        response = client.post(
            "/v1/chat/completions",
            json={**payload(), "stream": True},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = [line.removeprefix("data: ") for line in response.text.splitlines() if line]
    assert frames[-1] == "[DONE]"
    chunks = [json.loads(frame) for frame in frames[:-1]]
    assert chunks[0]["choices"][0]["delta"]["role"] == "assistant"
    assert (
        "".join(chunk["choices"][0]["delta"].get("content", "") for chunk in chunks)
        == "Try the quiet restaurant by the park."
    )
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["metadata"]["sources"][0]["chunk_id"] == str(CHUNK_ID)


def test_authentication_error_uses_openai_error_type_and_keeps_request_id_header() -> None:
    app, client = build_client()

    async def reject_authentication():
        raise AppError(401, "AUTH_REQUIRED", "Authentication is required")

    app.dependency_overrides[get_current_principal] = reject_authentication
    with client:
        response = client.post(
            "/v1/chat/completions",
            json=payload(),
            headers={"X-Request-ID": "sdk-request-1"},
        )

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "sdk-request-1"
    assert response.json() == {
        "error": {
            "message": "Authentication is required",
            "type": "authentication_error",
            "param": None,
            "code": "auth_required",
        }
    }
