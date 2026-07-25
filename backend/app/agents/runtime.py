"""Production assembly of ST-301 nodes on the executable LangGraph topology."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID, uuid4

from anyio import to_thread
from langgraph.runtime import Runtime

from app.agents.contracts import RetrievalRequest, RetrievalScope, RetrieverAdapter
from app.agents.generation import GroundedGeneration  # kept for _generate_general / _tool_guard
from app.agents.graph import ChatGraphNodes, build_chat_graph
from app.agents.memory import ConversationMemoryService, recent_conversation_history
from app.agents.persistence import GroundedResponsePersister
from app.agents.routing import ClarificationPlanner, ConstraintExtractor, IntentRouter
from app.agents.state import ChatState

if TYPE_CHECKING:
    from app.agents.langchain_rag import SimpleRAGGenerator
from app.agents.tools import (
    KnowledgeSearchResult,
    RegisteredToolPlanner,
    ToolArgumentsInvalid,
    ToolCallError,
    ToolExecutionContext,
    ToolExecutor,
    ToolPlanner,
)
from app.agents.types import ChatConstraints, SafetyDecision, SafetyResult, SourceCitation
from app.application.authorization import AuthorizationPrincipal
from app.application.content_safety import ContentDirection, ContentSafetyService
from app.application.conversations import (
    ConversationRepository,
    MessageInput,
    MessageRole,
    MessageStatus,
    MessageView,
)

_TOOL_HANDOFF_ANSWER = "这个请求需要调用受控工具；请通过已注册并授权的工具入口继续。"
_TOOL_EMPTY_ANSWER = "受控工具未在当前授权范围内找到可用结果。"
_BLOCKED_INPUT_ANSWER = "抱歉，这条请求包含受限内容，无法继续处理。"
_BLOCKED_OUTPUT_ANSWER = "抱歉，生成结果未通过安全检查，请调整问题后重试。"


class ModelRoutingDecision(Protocol):
    model_version_id: UUID


class ModelVersionRouter(Protocol):
    async def resolve(
        self, scene: str, environment: str, routing_key: str
    ) -> ModelRoutingDecision | None: ...


@dataclass(slots=True)
class ChatRunContext:
    owner_user_id: UUID
    retrieval_scope: RetrievalScope
    request_id: str
    parent_message_id: UUID | None
    model_version_id: UUID | None = None
    principal: AuthorizationPrincipal | None = None
    user_message: MessageView | None = None
    assistant_message: MessageView | None = None
    generation: GroundedGeneration | None = None


@dataclass(frozen=True, slots=True)
class ChatRunResult:
    state: ChatState
    message: MessageView
    generation: GroundedGeneration | None = None


class ChatAgentRuntime:
    """Execute one owned conversation turn and persist its immutable evidence snapshots."""

    def __init__(
        self,
        *,
        repository: ConversationRepository,
        memory: ConversationMemoryService,
        retriever: RetrieverAdapter,
        generator: SimpleRAGGenerator,
        safety: ContentSafetyService | None = None,
        router: IntentRouter | None = None,
        extractor: ConstraintExtractor | None = None,
        clarification: ClarificationPlanner | None = None,
        tool_executor: ToolExecutor | None = None,
        tool_planner: ToolPlanner | None = None,
        model_router: ModelVersionRouter | None = None,
        model_scene: str = "chat",
        model_environment: str = "development",
    ) -> None:
        self._repository = repository
        self._memory = memory
        self._retriever = retriever
        self._generator = generator
        self._safety = safety
        self._router = router or IntentRouter()
        self._extractor = extractor or ConstraintExtractor()
        self._clarification = clarification or ClarificationPlanner()
        self._tool_executor = tool_executor
        self._tool_planner = tool_planner or RegisteredToolPlanner()
        self._model_router = model_router
        self._model_scene = model_scene
        self._model_environment = model_environment
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
        principal: AuthorizationPrincipal | None = None,
    ) -> ChatRunResult:
        normalized = query.strip()
        if not normalized:
            raise ValueError("query must not be blank")
        conversation = await self._repository.get_conversation(conversation_id, owner_user_id)
        if principal is not None and principal.user_id != owner_user_id:
            raise PermissionError("chat principal does not own this runtime request")
        effective_request_id = request_id or str(uuid4())
        model_version_id = None
        if self._model_router is not None:
            routing = await self._model_router.resolve(
                self._model_scene,
                self._model_environment,
                f"{owner_user_id}:{conversation_id}:{effective_request_id}",
            )
            if routing is not None:
                model_version_id = routing.model_version_id
        context = ChatRunContext(
            owner_user_id=owner_user_id,
            retrieval_scope=retrieval_scope,
            request_id=effective_request_id,
            parent_message_id=conversation.current_branch_message_id,
            model_version_id=model_version_id,
            principal=principal,
        )
        result = await self.graph.ainvoke(
            {"conversation_id": str(conversation_id), "user_query": normalized},
            context=context,
        )
        if context.assistant_message is None:
            raise RuntimeError("chat graph completed without persisting an assistant message")
        return ChatRunResult(
            state=result,
            message=context.assistant_message,
            generation=context.generation,
        )

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
        window = await self._memory.restore(UUID(state["conversation_id"]), context.owner_user_id)
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
        scenario = window.conversation.settings.get("scenario")
        if isinstance(scenario, str) and scenario.strip():
            update["scene"] = scenario.strip()
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
            query=_contextualize_retrieval_query(
                state["user_query"], state.get("history_summary", "")
            ),
            scope=runtime.context.retrieval_scope,
            constraints=state.get("constraints", ChatConstraints()),
        )
        chunks = await to_thread.run_sync(self._retriever.retrieve, request)
        return {"retrieved_chunks": tuple(chunks)}

    async def _generate_grounded(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        chunks = state.get("retrieved_chunks", ())
        contextual_query = _query_with_resolved_reference(
            state["user_query"], state.get("history_summary", "")
        )
        gen = await to_thread.run_sync(
            self._generator.generate,
            contextual_query,
            chunks,
            state.get("history_summary", ""),
        )
        runtime.context.generation = GroundedGeneration(
            gen.answer, None, gen.sources, gen.model_version, gen.fallback_reason
        )
        return {"answer": gen.answer, "sources": gen.sources}

    async def _generate_general(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        gen = await to_thread.run_sync(
            self._generator.generate_general,
            state["user_query"],
            state.get("history_summary", ""),
        )
        runtime.context.generation = GroundedGeneration(
            gen.answer,
            None,
            (),
            gen.model_version,
            gen.fallback_reason or "general_chat",
        )
        return {"answer": gen.answer, "sources": ()}

    async def _tool_guard(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        context = runtime.context
        if self._tool_executor is None:
            context.generation = GroundedGeneration(
                _TOOL_HANDOFF_ANSWER, None, (), None, "tool_runtime_unavailable"
            )
            return {"answer": _TOOL_HANDOFF_ANSWER, "sources": ()}

        tool_context = ToolExecutionContext(
            actor_id=context.owner_user_id,
            request_id=context.request_id,
            conversation_id=UUID(state["conversation_id"]),
            retrieval_scope=context.retrieval_scope,
        )
        try:
            invocation = self._tool_planner.plan(state["user_query"])
        except ToolArgumentsInvalid as exc:
            try:
                await self._tool_executor.record_rejection(
                    name="invalid.tool_call",
                    arguments={},
                    context=tool_context,
                    error_code=exc.code,
                )
            except ToolCallError as audit_error:
                exc = audit_error
            generation = _tool_rejection_generation(exc.code)
        else:
            if context.principal is None:
                await self._tool_executor.record_rejection(
                    name=invocation.name,
                    arguments=invocation.arguments,
                    context=tool_context,
                    error_code="TOOL_AUTHORIZATION_DENIED",
                )
                generation = _tool_rejection_generation("TOOL_AUTHORIZATION_DENIED")
            else:
                try:
                    result = await self._tool_executor.invoke(
                        invocation.name,
                        invocation.arguments,
                        principal=context.principal,
                        context=tool_context,
                    )
                except ToolCallError as exc:
                    generation = _tool_rejection_generation(exc.code)
                else:
                    generation = _tool_result_generation(invocation.name, result)

        context.generation = generation
        return {"answer": generation.answer, "sources": generation.sources}

    async def _output_guard(
        self, state: ChatState, runtime: Runtime[ChatRunContext]
    ) -> dict[str, object]:
        answer = state.get("answer", "")
        if not answer:
            return {}
        safety = await self._check_safety(answer, ContentDirection.OUTPUT, state, runtime.context)
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
            model_version_id=context.model_version_id,
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


def _tool_rejection_generation(code: str) -> GroundedGeneration:
    answer = f"受控工具调用已拒绝（{code}）。"
    return GroundedGeneration(answer, None, (), None, f"tool_rejected:{code}")


def _tool_result_generation(name: str, result: object) -> GroundedGeneration:
    if name != "knowledge.search" or not isinstance(result, KnowledgeSearchResult):
        return _tool_rejection_generation("TOOL_RESULT_INVALID")
    if not result.chunks:
        return GroundedGeneration(_TOOL_EMPTY_ANSWER, None, (), f"tool:{name}", "tool_no_result")

    sources = tuple(
        SourceCitation(
            chunk_id=chunk.chunk_id,
            rank_no=rank,
            source_location=chunk.source_location,
            content_snapshot=chunk.content,
            score=chunk.score,
            evidence_id=f"S{rank}",
        )
        for rank, chunk in enumerate(result.chunks, start=1)
    )
    lines = ["受控工具查询结果："]
    lines.extend(
        f"- [S{rank}] {chunk.content.strip()}" for rank, chunk in enumerate(result.chunks, start=1)
    )
    return GroundedGeneration("\n".join(lines), None, sources, f"tool:{name}")


def _constraints_from_settings(settings: dict[str, object]) -> ChatConstraints | None:
    value = settings.get("constraints")
    if not isinstance(value, dict):
        return None
    try:
        return ChatConstraints(
            distance_meter_lte=_optional_int(value.get("distance_meter_lte")),
            budget_cent_per_person_lte=_optional_int(value.get("budget_cent_per_person_lte")),
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


_CONTEXTUAL_FOLLOW_UP_MARKERS = (
    "这家",
    "那家",
    "它",
    "他们",
    "第一家",
    "第二家",
    "第三家",
    "上一个",
    "下一个",
    "刚才",
    "前面",
    "上面",
    "换一家",
    "换一个",
    "再来一家",
    "还有吗",
    "便宜点",
    "贵一点",
    "差评",
    "人均多少",
    "怎么样",
)


def _contextualize_retrieval_query(query: str, history: str) -> str:
    """Expand context-dependent follow-ups while leaving standalone queries untouched."""
    normalized_query = query.strip()
    normalized_history = history.strip()
    if not normalized_history or not _is_contextual_follow_up(normalized_query):
        return normalized_query
    recent_history = recent_conversation_history(normalized_history, max_messages=2)
    contextual_query = _query_with_resolved_reference(normalized_query, normalized_history)
    return (
        "请根据以下同一会话语境检索当前追问涉及的商家和条件。\n"
        f"最近一轮对话：{recent_history[-4000:]}\n"
        f"当前追问：{contextual_query}"
    )


def _is_contextual_follow_up(query: str) -> bool:
    return any(marker in query for marker in _CONTEXTUAL_FOLLOW_UP_MARKERS) or (
        len(query) <= 16 and query.endswith(("呢", "吗", "？", "?"))
    )


_ORDINAL_INDICES = {
    "第一家": 1,
    "第二家": 2,
    "第三家": 3,
    "第四家": 4,
    "第五家": 5,
    "第一个": 1,
    "第二个": 2,
    "第三个": 3,
    "第四个": 4,
    "第五个": 5,
}
_NUMBERED_BOLD_ITEM = re.compile(r"(?m)^\s*(\d+)[.、]\s+\*\*([^*\n]{1,100})\*\*")
_NUMBERED_PLAIN_ITEM = re.compile(r"(?m)^\s*(\d+)[.、]\s+([^：:\n（(]{1,100})")


def _query_with_resolved_reference(query: str, history: str) -> str:
    reference = _resolve_ordinal_reference(query, history)
    if reference is None:
        return query
    marker, merchant_name = reference
    return f"{query}\n[会话指代解析：{marker}明确指“{merchant_name}”，不得重新排列商家顺序]"


def _resolve_ordinal_reference(query: str, history: str) -> tuple[str, str] | None:
    requested = next(
        ((marker, index) for marker, index in _ORDINAL_INDICES.items() if marker in query),
        None,
    )
    if requested is None:
        return None
    marker, requested_index = requested
    latest = recent_conversation_history(history, max_messages=1)
    numbered = {int(number): name.strip() for number, name in _NUMBERED_BOLD_ITEM.findall(latest)}
    if requested_index not in numbered:
        numbered.update(
            {
                int(number): name.strip().strip("* ")
                for number, name in _NUMBERED_PLAIN_ITEM.findall(latest)
            }
        )
    merchant_name = numbered.get(requested_index)
    if merchant_name:
        return marker, merchant_name

    inline = re.search(
        rf"{re.escape(marker)}\s*(?:是|为|：|:)\s*(?:\*\*)?([^，。；\n*]{{1,100}})",
        latest,
    )
    if inline is None:
        return None
    return marker, inline.group(1).strip()
