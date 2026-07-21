import asyncio
import threading
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi.testclient import TestClient

from app.application.authorization import AuthorizationPrincipal
from app.application.conversations import MessageRole, MessageStatus, MessageView, SourceView
from app.main import create_app

USER_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125")
CONVERSATION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b126")
MESSAGE_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b127")
CHUNK_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b128")


def _principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(USER_ID, "user", "User", None, USER_ID, (), (), ())


def _message() -> MessageView:
    return MessageView(
        MESSAGE_ID,
        CONVERSATION_ID,
        None,
        2,
        "assistant:req",
        MessageRole.ASSISTANT,
        "A quiet cafe.",
        MessageStatus.COMPLETED,
        None,
        3,
        4,
        10,
        None,
        datetime(2026, 7, 21, tzinfo=UTC),
        (SourceView(CHUNK_ID, 1, "review/1", "Quiet seats.", 0.9, None),),
    )


def _client(runtime=None):
    app = create_app(readiness_checks={})
    app.state.websocket_token_service = AsyncMock()
    app.state.websocket_token_service.consume.return_value = USER_ID
    app.state.authorization_repository = AsyncMock()
    app.state.authorization_repository.load_principal.return_value = _principal()
    app.state.agent_runtime = runtime or AsyncMock()
    app.state.agent_runtime.run.return_value = SimpleNamespace(
        state={"intent": "knowledge_query"}, message=_message()
    )
    app.state.websocket_heartbeat_interval = 30
    return app, TestClient(app)


def test_websocket_emits_ack_route_delta_sources_and_completed() -> None:
    _app, client = _client()
    with client, client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket:
        socket.send_json(
            {
                "type": "chat.request",
                "request_id": "req-1",
                "conversation_id": str(CONVERSATION_ID),
                "content": "quiet cafe",
            }
        )
        events = [socket.receive_json() for _ in range(5)]

    assert [event["type"] for event in events] == [
        "chat.ack",
        "chat.route",
        "chat.delta",
        "chat.sources",
        "chat.completed",
    ]
    assert events[-1]["message_id"] == str(MESSAGE_ID)


def test_websocket_cancel_cancels_downstream_task() -> None:
    cancelled = threading.Event()
    runtime = AsyncMock()

    async def run(**_kwargs):
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runtime.run.side_effect = run
    _app, client = _client(runtime)
    with client, client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket:
        socket.send_json(
            {
                "type": "chat.request",
                "request_id": "req-cancel",
                "conversation_id": str(CONVERSATION_ID),
                "content": "keep going",
            }
        )
        assert socket.receive_json()["type"] == "chat.ack"
        socket.send_json({"type": "chat.cancel", "request_id": "req-cancel"})
        completed = socket.receive_json()

    assert completed["finish_reason"] == "cancelled"
    assert cancelled.is_set()


def test_websocket_sends_heartbeat_and_accepts_pong() -> None:
    app, client = _client()
    app.state.websocket_heartbeat_interval = 0.05
    with client, client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket:
        first_ping = socket.receive_json()
        socket.send_json({"type": "pong"})
        second_ping = socket.receive_json()

    assert first_ping["type"] == "ping"
    assert second_ping["type"] == "ping"


def test_websocket_disconnect_cancels_downstream_task() -> None:
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
    _app, client = _client(runtime)
    with client:
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
