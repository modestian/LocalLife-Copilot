"""Story-level acceptance coverage for production-style controlled tool execution."""

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.agents.contracts import RetrievalScope
from app.agents.generation import GroundedRAGGenerator
from app.agents.local_model import ExtractiveModelAdapter
from app.agents.memory import MemoryWindow
from app.agents.runtime import ChatAgentRuntime
from app.agents.tools import ToolExecutor, ToolRegistry, knowledge_search_tool
from app.agents.types import RetrievedChunk
from app.api.dependencies.authorization import get_current_principal
from app.application.authorization import AuthorizationPrincipal, PermissionRule
from app.application.conversations import (
    ConversationStatus,
    ConversationView,
    MessageRole,
    MessageView,
)
from app.main import create_app


def _conversation() -> ConversationView:
    now = datetime.now(UTC)
    return ConversationView(
        id=uuid4(),
        owner_user_id=uuid4(),
        title=None,
        status=ConversationStatus.ACTIVE,
        memory_backend="MYSQL",
        current_branch_message_id=None,
        settings={},
        version=1,
        created_at=now,
        updated_at=now,
    )


def _message(conversation_id: UUID, role: MessageRole, content: str) -> MessageView:
    return MessageView(
        id=uuid4(),
        conversation_id=conversation_id,
        parent_message_id=None,
        sequence_no=1,
        request_id=None,
        role=role,
        content=content,
        status="COMPLETED",  # type: ignore[arg-type]
        model_version_id=None,
        prompt_tokens=None,
        completion_tokens=None,
        latency_ms=None,
        error_code=None,
        created_at=datetime.now(UTC),
    )


class RecordingRepository:
    def __init__(self, conversation: ConversationView) -> None:
        self.conversation = conversation
        self.payloads = []

    async def get_conversation(self, conversation_id: UUID, owner_user_id: UUID):
        assert conversation_id == self.conversation.id
        assert owner_user_id == self.conversation.owner_user_id
        return self.conversation

    async def append_message(self, conversation_id: UUID, owner_user_id: UUID, payload):
        del owner_user_id
        self.payloads.append(payload)
        message = _message(conversation_id, payload.role, payload.content)
        return replace(message, sources=payload.sources)

    async def update_settings(self, *_args, **_kwargs):
        return self.conversation


class RecordingRetriever:
    def __init__(self) -> None:
        self.requests = []
        self.chunk = RetrievedChunk(
            chunk_id=str(uuid4()),
            content="蜀香小馆环境安静，适合两人用餐。",
            score=0.95,
            source_location="reviews/shuxiang/1",
        )

    def retrieve(self, request):
        self.requests.append(request)
        return (self.chunk,)


class RecordingAudit:
    def __init__(self) -> None:
        self.rows: list[dict[str, object]] = []

    async def append_tool_audit(self, **values: object) -> None:
        self.rows.append(values)


def _principal(user_id: UUID, *, allowed: bool = True) -> AuthorizationPrincipal:
    permissions = (PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),) if allowed else ()
    return AuthorizationPrincipal(
        user_id=user_id,
        username="tool-user",
        display_name="Tool User",
        email=None,
        department_id=uuid4(),
        roles=(),
        permissions=permissions,
        resource_grants=(),
    )


def _runtime(conversation: ConversationView):
    repository = RecordingRepository(conversation)
    memory = AsyncMock()
    memory.restore.return_value = MemoryWindow(conversation, (), "", None, 0)
    retriever = RecordingRetriever()
    registry = ToolRegistry()
    registry.register(knowledge_search_tool(retriever))
    audit = RecordingAudit()
    runtime = ChatAgentRuntime(
        repository=repository,  # type: ignore[arg-type]
        memory=memory,
        retriever=retriever,
        generator=GroundedRAGGenerator(ExtractiveModelAdapter()),
        tool_executor=ToolExecutor(registry, audit),
    )
    return runtime, repository, retriever, audit


def _scope() -> RetrievalScope:
    return RetrievalScope("tenant-1", frozenset(), frozenset())


async def _run(runtime, conversation, query: str, *, allowed: bool = True):
    return await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query=query,
        retrieval_scope=_scope(),
        request_id="tool-runtime-request",
        principal=_principal(conversation.owner_user_id, allowed=allowed),
    )


async def test_runtime_executes_registered_tool_with_trusted_scope_and_audit() -> None:
    conversation = _conversation()
    runtime, repository, retriever, audit = _runtime(conversation)

    result = await _run(runtime, conversation, "调用工具：搜索安静川菜")

    assert "蜀香小馆" in result.message.content
    assert retriever.requests[0].scope == _scope()
    assert retriever.requests[0].query == "搜索安静川菜"
    assert repository.payloads[-1].sources[0].chunk_id == UUID(retriever.chunk.chunk_id)
    assert audit.rows[0]["result"] == "SUCCEEDED"
    assert audit.rows[0]["summary"]["tool_name"] == "knowledge.search"


@pytest.mark.parametrize(
    ("query", "allowed", "error_code"),
    [
        (
            '调用工具：{"name":"system.exec","arguments":{"command":"whoami"}}',
            True,
            "TOOL_NOT_REGISTERED",
        ),
        (
            '调用工具：{"name":"knowledge.search","arguments":{"query":"川菜","command":"whoami"}}',
            True,
            "TOOL_ARGUMENTS_INVALID",
        ),
        ("调用工具：搜索安静川菜", False, "TOOL_AUTHORIZATION_DENIED"),
        ('调用工具：{"name":"knowledge.search"', True, "TOOL_ARGUMENTS_INVALID"),
    ],
)
async def test_runtime_rejects_and_audits_unsafe_tool_calls(
    query: str, allowed: bool, error_code: str
) -> None:
    conversation = _conversation()
    runtime, repository, retriever, audit = _runtime(conversation)

    result = await _run(runtime, conversation, query, allowed=allowed)

    assert error_code in result.message.content
    assert not retriever.requests
    assert repository.payloads[-1].sources == ()
    assert audit.rows[0]["result"] == "BLOCKED"
    assert audit.rows[0]["summary"]["error_code"] == error_code
    assert "whoami" not in str(audit.rows)


def _transport_app(conversation: ConversationView):
    runtime, repository, retriever, audit = _runtime(conversation)
    principal = _principal(conversation.owner_user_id)
    app = create_app(readiness_checks={})
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.state.conversation_repository = repository
    app.state.conversation_memory = AsyncMock()
    app.state.agent_runtime = runtime
    app.state.websocket_token_service = AsyncMock()
    app.state.websocket_token_service.consume.return_value = principal.user_id
    app.state.authorization_repository = AsyncMock()
    app.state.authorization_repository.load_principal.return_value = principal
    return app, retriever, audit


def test_openai_transport_executes_the_registered_tool_chain() -> None:
    conversation = _conversation()
    app, retriever, audit = _transport_app(conversation)

    with TestClient(app) as client:
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "local-life-assistant",
                "messages": [{"role": "user", "content": "调用工具：搜索安静川菜"}],
                "conversation_id": str(conversation.id),
            },
        )

    assert response.status_code == 200
    assert "蜀香小馆" in response.json()["choices"][0]["message"]["content"]
    assert response.json()["sources"][0]["chunk_id"] == retriever.chunk.chunk_id
    assert audit.rows[0]["result"] == "SUCCEEDED"


def test_websocket_transport_executes_tool_and_sends_first_packet_within_two_seconds() -> None:
    conversation = _conversation()
    app, _retriever, audit = _transport_app(conversation)

    with (
        TestClient(app) as client,
        client.websocket_connect("/api/v1/ws/chat?access_token=once") as socket,
    ):
        started = datetime.now(UTC)
        socket.send_json(
            {
                "type": "chat.request",
                "request_id": "tool-websocket-request",
                "conversation_id": str(conversation.id),
                "content": "调用工具：搜索安静川菜",
            }
        )
        ack = socket.receive_json()
        first_packet_seconds = (datetime.now(UTC) - started).total_seconds()
        events = [socket.receive_json() for _ in range(4)]

    assert ack["type"] == "chat.ack"
    assert first_packet_seconds < 2
    assert [event["type"] for event in events] == [
        "chat.route",
        "chat.delta",
        "chat.sources",
        "chat.completed",
    ]
    assert audit.rows[0]["result"] == "SUCCEEDED"
