"""Production assembly of ST-301 nodes on the executable LangGraph topology."""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from uuid import UUID, uuid4

from anyio import to_thread
from langgraph.runtime import Runtime

from app.agents.contracts import RetrievalRequest, RetrievalScope, RetrieverAdapter
from app.agents.generation import GroundedGeneration, GroundedRAGGenerator
from app.agents.graph import ChatGraphNodes, build_chat_graph
from app.agents.memory import ConversationMemoryService
from app.agents.persistence import GroundedResponsePersister
from app.agents.routing import ClarificationPlanner, ConstraintExtractor, IntentRouter
from app.agents.state import ChatState
from app.agents.types import ChatConstraints, SafetyDecision, SafetyResult
from app.application.content_safety import ContentDirection, ContentSafetyService
from app.application.conversations import (
    ConversationRepository,
    MessageInput,
    MessageRole,
    MessageStatus,
    MessageView,
)

_GENERAL_ANSWER = "你好！我可以帮你按距离、预算、菜系、氛围和用餐场景寻找商家。"
_TOOL_HANDOFF_ANSWER = "这个请求需要调用受控工具；请通过已注册并授权的工具入口继续。"
_BLOCKED_INPUT_ANSWER = "抱歉，这条请求包含受限内容，无法继续处理。"
_BLOCKED_OUTPUT_ANSWER = "抱歉，生成结果未通过安全检查，请调整问题后重试。"


@dataclass(slots=True)
class ChatRunContext:
    owner_user_id: UUID
    retrieval_scope: RetrievalScope
    request_id: str
    parent_message_id: UUID | None
    user_message: MessageView | None = None
    assistant_message: MessageView | None = None
    generation: GroundedGeneration | None = None


@dataclass(frozen=True, slots=True)
class ChatRunResult:
    state: ChatState
    message: MessageView


class ChatAgentRuntime:
    """Execute one owned conversation turn and persist its immutable evidence snapshots."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        memory: ConversationMemoryService,
        retriever: RetrieverAdapter,
        generator: GroundedRAGGenerator,
        safety: ContentSafetyService | None = None,
        router: IntentRouter | None = None,
        extractor: ConstraintExtractor | None = None,
        clarification: ClarificationPlanner | None = None,
    ) -> None:
        self._repository = repository
        self._memory = memory
        self._retriever = retriever
        self._generator = generator
        self._safety = safety
        self._router = router or IntentRouter()
        self._extractor = extractor or ConstraintExtractor()
        self._clarification = clarification or ClarificationPlanner()
        self._persister = GroundedResponsePersister(repository)
        self.graph = build_chat_graph(
            ChatGraphNodes(
                input_guard=self._input_guard,
                load_memory=self._load_memory,
                route_intent=self._route_intent,
                extract_constraints=self._extract_constraints,
                ask_question=self._ask_question,
                hybrid_retrieve=self._hybrid_retrieve,
                generate_grounded=self._generate_grounded,
                generate_general=self._generate_general,
                tool_guard=self._tool_guard,
                output_guard=self._output_guard,
                persist=self._persist,
            ),
            context_schema=ChatRunContext,
        )

    async def run(
        self,
        *,
        conversation_id: UUID,
        owner_user_id: UUID,
        query: str,
        retrieval_scope: RetrievalScope,
        request_id: str | None = None,
    ) -> ChatRunResult:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        conversation = await self._repository.get_conversation(conversation_id, owner_user_id)
        context = ChatRunContext(
            owner_user_id=owner_user_id,
            retrieval_scope=retrieval_scope,
            request_id=request_id or str(uuid4()),
            parent_message_id=conversation.current_branch_message_id,
        )
        result = await self.graph.ainvoke(
            {"conversation_id": str(conversation_id), "user_query": normalized},
            context=context,
        )
        if context.assistant_message is None:
            raise RuntimeError("chat graph completed without persisting an assistant message")
        return ChatRunResult(state=result, message=context.assistant_message)

    async def _input_guard(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        context = runtime.context
        safety = await self._check_safety(
            state["user_query"], ContentDirection.INPUT, state, context
        )
        if safety.decision is SafetyDecision.BLOCK:
            context.generation = GroundedGeneration(
                _BLOCKED_INPUT_ANSWER, None, (), None, "blocked_input"
            )
            return {"safety_result": safety, "answer": _BLOCKED_INPUT_ANSWER, "sources": ()}
        context.user_message = await self._repository.append_message(
            UUID(state["conversation_id"]),
            context.owner_user_id,
            MessageInput(
                role=MessageRole.USER,
                content=state["user_query"],
                status=MessageStatus.COMPLETED,
                parent_message_id=context.parent_message_id,
                request_id=context.request_id,
            ),
        )
        context.parent_message_id = context.user_message.id
        await self._memory.invalidate(UUID(state["conversation_id"]))
        return {"safety_result": safety}

    async def _load_memory(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        context = runtime.context
        window = await self._memory.restore(
            UUID(state["conversation_id"]), context.owner_user_id
        )
        recent = [
            message
            for message in window.messages
            if context.user_message is None or message.id != context.user_message.id
        ]
        parts = [window.history_summary] if window.history_summary else []
        parts.extend(f"{message.role.value}: {message.content}" for message in recent)
        update: dict[str, object] = {"history_summary": "\n".join(parts)}
        constraints = _constraints_from_settings(window.conversation.settings)
        if constraints is not None:
            update["constraints"] = constraints
        return update

    def _route_intent(
        self, state: ChatState, _runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        return self._router(state)

    def _extract_constraints(
        self, state: ChatState, _runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        return self._extractor(state)

    def _ask_question(
        self, state: ChatState, _runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        return self._clarification(state)

    async def _hybrid_retrieve(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        request = RetrievalRequest(
            query=state["user_query"],
            scope=runtime.context.retrieval_scope,
            constraints=state.get("constraints", ChatConstraints()),
        )
        chunks = await to_thread.run_sync(self._retriever.retrieve, request)
        return {"retrieved_chunks": tuple(chunks)}

    async def _generate_grounded(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        generation = await to_thread.run_sync(self._generator.generate, state)
        runtime.context.generation = generation
        return {"answer": generation.answer, "sources": generation.sources}

    def _generate_general(
        self, _state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        runtime.context.generation = GroundedGeneration(
            _GENERAL_ANSWER, None, (), None, "general_chat"
        )
        return {"answer": _GENERAL_ANSWER, "sources": ()}

    def _tool_guard(
        self, _state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        runtime.context.generation = GroundedGeneration(
            _TOOL_HANDOFF_ANSWER, None, (), None, "tool_handoff"
        )
        return {"answer": _TOOL_HANDOFF_ANSWER, "sources": ()}

    async def _output_guard(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        answer = state.get("answer", "")
        if not answer:
            return {}
        safety = await self._check_safety(
            answer, ContentDirection.OUTPUT, state, runtime.context
        )
        if safety.decision is SafetyDecision.BLOCK:
            runtime.context.generation = GroundedGeneration(
                _BLOCKED_OUTPUT_ANSWER, None, (), None, "blocked_output"
            )
            return {
                "answer": _BLOCKED_OUTPUT_ANSWER,
                "sources": (),
                "safety_result": safety,
            }
        return {"safety_result": safety}

    async def _persist(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        context = runtime.context
        generation = context.generation
        if generation is None or generation.answer != state.get("answer"):
            generation = GroundedGeneration(
                state["answer"],
                None,
                tuple(state.get("sources", ())),
                None,
                None if state.get("sources") else "non_grounded_response",
            )
        context.assistant_message = await self._persister.persist(
            UUID(state["conversation_id"]),
            context.owner_user_id,
            generation,
            request_id=_assistant_request_id(context.request_id),
            parent_message_id=context.parent_message_id,
        )
        constraints = state.get("constraints")
        if constraints is not None:
            await self._repository.update_settings(
                UUID(state["conversation_id"]),
                context.owner_user_id,
                {"constraints": asdict(constraints)},
            )
        await self._memory.invalidate(UUID(state["conversation_id"]))
        return {}

    async def _check_safety(
        self,
        content: str,
        direction: ContentDirection,
        state: ChatState,
        context: ChatRunContext,
    ) -> SafetyResult:
        if self._safety is None:
            return SafetyResult(SafetyDecision.ALLOW)
        result = await self._safety.check(
            content=content,
            direction=direction,
            actor_id=context.owner_user_id,
            request_id=context.request_id,
            conversation_id=UUID(state["conversation_id"]),
        )
        return SafetyResult(
            SafetyDecision.ALLOW if result.allowed else SafetyDecision.BLOCK,
            tuple(str(value) for value in result.matched_rule_ids),
        )


def _assistant_request_id(request_id: str) -> str:
    return "assistant:" + hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:32]


def _constraints_from_settings(settings: dict[str, object]) -> ChatConstraints | None:
    value = settings.get("constraints")
    if not isinstance(value, dict):
        return None
    try:
        return ChatConstraints(
            distance_meter_lte=_optional_int(value.get("distance_meter_lte")),
            budget_cent_per_person_lte=_optional_int(
                value.get("budget_cent_per_person_lte")
            ),
            cuisines=_string_tuple(value.get("cuisines")),
            atmospheres=_string_tuple(value.get("atmospheres")),
            scenes=_string_tuple(value.get("scenes")),
            party_size=_optional_int(value.get("party_size")),
            open_now=value.get("open_now") if isinstance(value.get("open_now"), bool) else None,
        )
    except (TypeError, ValueError):
        return None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())