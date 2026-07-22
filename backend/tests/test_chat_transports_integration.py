"""Integration coverage for the public chat transport contracts.

The tests cross the SDK/HTTP/WebSocket boundaries while replacing only the
shared agent runtime, so they stay deterministic without an external model.
"""

import asyncio
import json
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import AsyncOpenAI, NotFoundError

from app.api.dependencies.authorization import get_current_principal
from app.application.authorization import AuthorizationPrincipal
from app.application.conversations import MessageRole, MessageStatus, MessageView, SourceView
from app.main import create_app

USER_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125")
TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b121")
CONVERSATION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b126")
MESSAGE_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b127")
CHUNK_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b128")


def _principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=USER_ID,
        username="integration-user",
        display_name="Integration User",
        email=None,
        department_id=TENANT_ID,
        roles=(),
        permissions=(),
        resource_grants=(),
    )


def _message(content: str = "Try the quiet restaurant by the park.") -> MessageView:
    return MessageView(
        id=MESSAGE_ID,
        conversation_id=CONVERSATION_ID,
        parent_message_id=None,
        sequence_no=2,
        request_id="assistant:integration-request",
        role=MessageRole.ASSISTANT,
        content=content,
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


def _app(runtime=None):
    app = create_app(readiness_checks={})
    app.dependency_overrides[get_current_principal] = _principal
    app.state.conversation_repository = AsyncMock()
    app.state.conversation_memory = AsyncMock()
    app.state.agent_runtime = runtime or AsyncMock()
    app.state.agent_runtime.run.return_value = SimpleNamespace(
        state={"intent": "knowledge_query"}, message=_message()
    )
    app.state.websocket_token_service = AsyncMock()
    app.state.websocket_token_service.consume.return_value = USER_ID
    app.state.authorization_repository = AsyncMock()
    app.state.authorization_repository.load_principal.return_value = _principal()
    app.state.websocket_heartbeat_interval = 30
    return app


def _request_kwargs(**overrides):
    kwargs = {
        "model": "local-life-assistant",
        "messages": [{"role": "user", "content": "Where should we eat?"}],
        "extra_body": {"conversation_id": str(CONVERSATION_ID)},
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_openai_sdk_parses_non_streaming_and_streaming_responses() -> None:
    app = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        sdk = AsyncOpenAI(
            api_key="integration-test-key",
            base_url="http://test/v1",
            http_client=http_client,
        )

        completion = await sdk.chat.completions.create(**_request_kwargs())
        stream = await sdk.chat.completions.create(**_request_kwargs(stream=True))
        chunks = [chunk async for chunk in stream]

    assert completion.id == f"chatcmpl-{MESSAGE_ID}"
    assert completion.choices[0].message.content == _message().content
    assert completion.usage is not None
    assert completion.usage.total_tokens == 20

    assert chunks[0].choices[0].delta.role == "assistant"
    assert "".join(chunk.choices[0].delta.content or "" for chunk in chunks) == _message().content
    assert [chunk.choices[0].finish_reason for chunk in chunks] == [None, None, "stop"]
    assert chunks[-1].model_extra["metadata"]["sources"][0]["chunk_id"] == str(CHUNK_ID)


@pytest.mark.asyncio
async def test_openai_sdk_receives_compatible_error_object() -> None:
    app = _app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
        sdk = AsyncOpenAI(
            api_key="integration-test-key",
            base_url="http://test/v1",
            http_client=http_client,
        )
        with pytest.raises(NotFoundError) as caught:
            await sdk.chat.completions.create(**_request_kwargs(model="missing-model"))

    assert caught.value.status_code == 404
    assert caught.value.body == {
        "message": "The model 'missing-model' does not exist or is not available",
        "type": "invalid_request_error",
        "param": "model",
        "code": "model_not_found",
    }


@pytest.mark.asyncio
async def test_sse_runtime_exception_emits_error_then_done() -> None:
    runtime = AsyncMock()
    runtime.run.side_effect = TimeoutError()
    app = _app(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "local-life-assistant",
                "messages": [{"role": "user", "content": "Where should we eat?"}],
                "conversation_id": str(CONVERSATION_ID),
                "stream": True,
            },
        )

    frames = [line.removeprefix("data: ") for line in response.text.splitlines() if line]
    assert json.loads(frames[0])["object"] == "chat.completion.chunk"
    assert json.loads(frames[1]) == {
        "error": {
            "message": "The chat request timed out",
            "type": "server_error",
            "param": None,
            "code": "chat_timeout",
        }
    }
    assert frames[2] == "[DONE]"


def test_websocket_error_is_terminal_and_next_request_can_run() -> None:
    runtime = AsyncMock()
    runtime.run.side_effect = [
        TimeoutError(),
        SimpleNamespace(state={"intent": "knowledge_query"}, message=_message("ok")),
    ]
    app = _app(runtime)

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket,
    ):
        socket.send_json(
            {
                "type": "chat.request",
                "request_id": "req-timeout",
                "conversation_id": str(CONVERSATION_ID),
                "content": "first request",
            }
        )
        first_events = [socket.receive_json(), socket.receive_json()]

        socket.send_json(
            {
                "type": "chat.request",
                "request_id": "req-after-error",
                "conversation_id": str(CONVERSATION_ID),
                "content": "second request",
            }
        )
        second_events = [socket.receive_json() for _ in range(5)]

    assert [event["type"] for event in first_events] == ["chat.ack", "chat.error"]
    assert first_events[-1] == {
        "type": "chat.error",
        "code": "CHAT_TIMEOUT",
        "message": "The chat request timed out",
        "retryable": True,
        "request_id": "req-timeout",
    }
    assert [event["type"] for event in second_events] == [
        "chat.ack",
        "chat.route",
        "chat.delta",
        "chat.sources",
        "chat.completed",
    ]


def test_websocket_disconnect_cancels_the_shared_runtime() -> None:
    started = threading.Event()
    cancelled = threading.Event()
    runtime = AsyncMock()

    async def run(**_kwargs):
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runtime.run.side_effect = run
    app = _app(runtime)

    with TestClient(app) as client:
        with client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket:
            socket.send_json(
                {
                    "type": "chat.request",
                    "request_id": "req-disconnect",
                    "conversation_id": str(CONVERSATION_ID),
                    "content": "keep going",
                }
            )
            assert socket.receive_json()["type"] == "chat.ack"
            assert started.wait(1)

        assert cancelled.wait(1)
