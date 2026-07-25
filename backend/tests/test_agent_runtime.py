from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

from app.agents.contracts import RetrievalScope
from app.agents.langchain_rag import RAGGeneration, SimpleRAGGenerator
from app.agents.memory import MemoryWindow
from app.agents.runtime import ChatAgentRuntime
from app.agents.types import RetrievedChunk
from app.application.content_safety import ContentCheckResult, ContentDirection
from app.application.conversations import (
    ConversationStatus,
    ConversationView,
    MessageRole,
    MessageView,
)


def _conversation(*, settings: dict[str, object] | None = None) -> ConversationView:
    now = datetime.now(UTC)
    return ConversationView(
        id=uuid4(),
        owner_user_id=uuid4(),
        title=None,
        status=ConversationStatus.ACTIVE,
        memory_backend="MYSQL",
        current_branch_message_id=None,
        settings=settings or {},
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
        self.settings_updates: list[dict[str, object]] = []

    async def get_conversation(self, conversation_id: UUID, owner_user_id: UUID):
        assert conversation_id == self.conversation.id
        assert owner_user_id == self.conversation.owner_user_id
        return self.conversation

    async def append_message(self, conversation_id: UUID, owner_user_id: UUID, payload):
        self.payloads.append(payload)
        return _message(conversation_id, payload.role, payload.content)

    async def update_settings(
        self, conversation_id: UUID, owner_user_id: UUID, settings: dict[str, object]
    ):
        self.settings_updates.append(settings)
        return self.conversation


class RecordingRetriever:
    def __init__(self) -> None:
        self.requests = []
        self.chunk = RetrievedChunk(
            chunk_id=str(uuid4()),
            content="蜀香小馆提供川菜，环境安静，适合两人用餐。",
            score=0.95,
            source_location="reviews/shuxiang/1",
            merchant_id="merchant-shuxiang",
            data_updated_at="2026-07-21T08:00:00Z",
            metadata={
                "merchant_name": "蜀香小馆",
                "category": "川菜",
                "avg_price_cent": 8800,
                "business_status": "OPEN",
            },
        )

    def retrieve(self, request):
        self.requests.append(request)
        return (self.chunk,)


class RecordingModelRouter:
    def __init__(self, model_version_id: UUID) -> None:
        self.model_version_id = model_version_id
        self.calls: list[tuple[str, str, str]] = []

    async def resolve(self, scene: str, environment: str, routing_key: str):
        self.calls.append((scene, environment, routing_key))
        return SimpleNamespace(model_version_id=self.model_version_id)


class FakeSimpleRAGGenerator(SimpleRAGGenerator):
    """Test double that returns chunk content without needing LangChain / Bailian."""

    def __init__(self) -> None:
        # Skip parent __init__ which requires LangChainRAGAdapter
        pass

    def generate(self, query: str, chunks: tuple[RetrievedChunk, ...]) -> RAGGeneration:
        from app.agents.langchain_rag import NO_EVIDENCE_ANSWER, chunks_to_citations

        citations = chunks_to_citations(chunks)
        if not chunks:
            return RAGGeneration(
                answer=NO_EVIDENCE_ANSWER, sources=(), fallback_reason="no_evidence"
            )
        return RAGGeneration(
            answer=chunks[0].content,
            sources=citations,
            model_version="test-stub",
        )


def _runtime(conversation: ConversationView):
    repository = RecordingRepository(conversation)
    memory = AsyncMock()
    memory.restore.return_value = MemoryWindow(conversation, (), "", None, 0)
    retriever = RecordingRetriever()
    model_router = RecordingModelRouter(uuid4())
    runtime = ChatAgentRuntime(
        repository=repository,  # type: ignore[arg-type]
        memory=memory,
        retriever=retriever,
        generator=FakeSimpleRAGGenerator(),
        model_router=model_router,  # type: ignore[arg-type]
    )
    return runtime, repository, memory, retriever, model_router


def _scope() -> RetrievalScope:
    return RetrievalScope(
        tenant_id="tenant-1",
        knowledge_base_ids=frozenset({"kb-1"}),
        resource_scopes=frozenset({"KNOWLEDGE_BASE:kb-1"}),
    )


async def test_runtime_asks_for_missing_conditions_and_persists_turn() -> None:
    """A bare recommendation without any constraint still triggers clarification."""
    conversation = _conversation()
    runtime, repository, _memory, retriever, model_router = _runtime(conversation)

    result = await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query="推荐一下",  # no concrete constraint → clarification needed
        retrieval_scope=_scope(),
        request_id="turn-1",
    )

    assert "人均预算" in result.message.content
    assert "用餐人数" in result.message.content
    assert not retriever.requests
    assert [payload.role for payload in repository.payloads] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert repository.payloads[-1].model_version_id == model_router.model_version_id
    assert model_router.calls[0][:2] == ("chat", "development")


async def test_runtime_restores_constraints_then_retrieves_generates_and_cites() -> None:
    conversation = _conversation(
        settings={
            "constraints": {
                "distance_meter_lte": 1000,
                "cuisines": ["川菜"],
                "atmospheres": ["安静"],
            }
        }
    )
    runtime, repository, _memory, retriever, _model_router = _runtime(conversation)

    result = await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query="两个人，人均 100 元以内",
        retrieval_scope=_scope(),
        request_id="turn-2",
    )

    assert "蜀香小馆" in result.message.content
    assert repository.payloads[-1].sources[0].source_location_snapshot == "reviews/shuxiang/1"
    assert retriever.requests[0].constraints.cuisines == ("川菜",)
    assert retriever.requests[0].constraints.party_size == 2
    assert retriever.requests[0].constraints.budget_cent_per_person_lte == 10000
    assert repository.settings_updates[-1]["constraints"]["party_size"] == 2


async def test_runtime_rebuilds_constraints_without_assistant_recommendation_terms() -> None:
    conversation = _conversation(
        settings={
            "constraints": {
                "distance_meter_lte": 3000,
                "budget_cent_per_person_lte": 8000,
                "cuisines": ["咖啡"],
                "atmospheres": ["安静"],
                "party_size": 2,
                "open_now": True,
            }
        }
    )
    runtime, repository, memory, retriever, _model_router = _runtime(conversation)
    memory.restore.return_value = MemoryWindow(
        conversation,
        (
            _message(
                conversation.id,
                MessageRole.USER,
                "我要找店\n\n"
                "[探店条件] 场景：附近随便吃；距离：3 公里内；预算：人均 80 元以内；"
                "人数：2 人；营业状态：当前营业",
            ),
            _message(
                conversation.id,
                MessageRole.ASSISTANT,
                "推荐书香咖啡馆，环境安静。",
            ),
        ),
        "",
        None,
        0,
    )

    await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query="清河面馆",
        retrieval_scope=_scope(),
        request_id="turn-merchant-name",
    )

    constraints = retriever.requests[0].constraints
    assert constraints.cuisines == ("面食",)
    assert constraints.atmospheres == ()
    assert constraints.distance_meter_lte == 3000
    assert constraints.budget_cent_per_person_lte == 8000
    assert constraints.party_size == 2
    assert repository.settings_updates[-1]["constraints"]["cuisines"] == ("面食",)
    assert repository.settings_updates[-1]["constraints"]["atmospheres"] == ()


class EmptyRetriever:
    def retrieve(self, _request):
        return ()


class BlockingInputSafety:
    async def check(self, *, content, direction, actor_id, request_id, conversation_id):
        del content, actor_id, request_id, conversation_id
        allowed = direction is ContentDirection.OUTPUT
        return ContentCheckResult(
            allowed=allowed,
            direction=direction,
            matched_rule_ids=() if allowed else (uuid4(),),
            decision="ALLOW" if allowed else "BLOCK_INPUT",
        )


async def test_runtime_persists_low_evidence_fallback_without_sources() -> None:
    conversation = _conversation(
        settings={"constraints": {"budget_cent_per_person_lte": 10000, "party_size": 2}}
    )
    repository = RecordingRepository(conversation)
    memory = AsyncMock()
    memory.restore.return_value = MemoryWindow(conversation, (), "", None, 0)
    runtime = ChatAgentRuntime(
        repository=repository,  # type: ignore[arg-type]
        memory=memory,
        retriever=EmptyRetriever(),
        generator=FakeSimpleRAGGenerator(),
    )

    result = await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query="推荐川菜餐厅",
        retrieval_scope=_scope(),
        request_id="no-result",
    )

    assert "当前资料不足" in result.message.content
    assert repository.payloads[-1].sources == ()


async def test_blocked_input_is_not_persisted_and_safe_refusal_is_persisted() -> None:
    conversation = _conversation()
    repository = RecordingRepository(conversation)
    memory = AsyncMock()
    memory.restore.return_value = MemoryWindow(conversation, (), "", None, 0)
    runtime = ChatAgentRuntime(
        repository=repository,  # type: ignore[arg-type]
        memory=memory,
        retriever=EmptyRetriever(),
        generator=FakeSimpleRAGGenerator(),
        safety=BlockingInputSafety(),  # type: ignore[arg-type]
    )

    result = await runtime.run(
        conversation_id=conversation.id,
        owner_user_id=conversation.owner_user_id,
        query="受限输入",
        retrieval_scope=_scope(),
        request_id="blocked-input",
    )

    assert "受限内容" in result.message.content
    assert [payload.role for payload in repository.payloads] == [MessageRole.ASSISTANT]
    assert repository.payloads[0].sources == ()
