"""Authenticated WebSocket transport for the shared chat runtime."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agents.generation import GenerationMode
from app.agents.types import ChatIntent
from app.api.openai import _shared_retrieval_scope, _source_data, _text_chunks, _usage_data
from app.application.authorization import AuthorizationPrincipal
from app.application.conversations import ConversationNotFound
from app.application.websocket_tokens import InvalidWebSocketToken
from app.core.errors import AppError

router = APIRouter(tags=["websocket-chat"])
logger = logging.getLogger(__name__)


class ChatOptionsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=50)


class ChatRequestEventDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    type: Literal["chat.request"]
    request_id: str = Field(min_length=1, max_length=128)
    conversation_id: UUID
    content: str = Field(min_length=1, max_length=100000)
    options: ChatOptionsDTO = Field(default_factory=ChatOptionsDTO)


class ChatCancelEventDTO(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)
    type: Literal["chat.cancel"]
    request_id: str = Field(min_length=1, max_length=128)


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket, access_token: str = "") -> None:
    principal = await _authenticate_socket(websocket, access_token)
    if principal is None:
        return
    await websocket.accept()

    send_lock = asyncio.Lock()
    configured_heartbeat = float(getattr(websocket.app.state, "websocket_heartbeat_interval", 30.0))
    heartbeat_interval = min(30.0, max(0.01, configured_heartbeat))
    last_pong = time.monotonic()
    active_task: asyncio.Task[None] | None = None
    active_request_id: str | None = None
    completed: dict[str, list[dict[str, Any]]] = {}
    disconnected = False

    async def send(payload: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def heartbeat() -> None:
        nonlocal last_pong
        while True:
            await asyncio.sleep(heartbeat_interval)
            if time.monotonic() - last_pong > heartbeat_interval * 2.5:
                await websocket.close(code=1001, reason="heartbeat timeout")
                return
            await send({"type": "ping", "timestamp": int(time.time())})

    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        while True:
            try:
                payload = await websocket.receive_json()
            except ValueError:
                await send(_chat_error("INVALID_EVENT", "Event must be valid JSON", False))
                continue
            event_type = payload.get("type") if isinstance(payload, dict) else None
            if event_type == "pong":
                last_pong = time.monotonic()
                continue
            if event_type == "chat.cancel":
                try:
                    cancel = ChatCancelEventDTO.model_validate(payload)
                except ValidationError as exc:
                    await send(_validation_error(exc))
                    continue
                if active_task is not None and cancel.request_id == active_request_id:
                    active_task.cancel()
                continue
            if event_type != "chat.request":
                await send(_chat_error("INVALID_EVENT", "Unsupported WebSocket event", False))
                continue
            try:
                chat_request = ChatRequestEventDTO.model_validate(payload)
            except ValidationError as exc:
                await send(_validation_error(exc))
                continue

            if active_task is not None and not active_task.done():
                if chat_request.request_id == active_request_id:
                    await send(
                        {"type": "chat.ack", "request_id": active_request_id, "resumed": True}
                    )
                else:
                    await send(
                        _chat_error(
                            "REQUEST_IN_PROGRESS",
                            "Another chat request is already in progress",
                            True,
                            chat_request.request_id,
                        )
                    )
                continue

            await send({"type": "chat.ack", "request_id": chat_request.request_id})
            replay = completed.get(chat_request.request_id)
            if replay is not None:
                for event in replay:
                    await send(event)
                continue
            active_request_id = chat_request.request_id
            active_task = asyncio.create_task(
                _serve_request(websocket, principal, chat_request, send, completed)
            )
    except (WebSocketDisconnect, RuntimeError):
        disconnected = True
    finally:
        heartbeat_task.cancel()
        if active_task is not None and not active_task.done():
            active_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await heartbeat_task
        if active_task is not None:
            with suppress(asyncio.CancelledError, Exception):
                await active_task
        if not disconnected:
            with suppress(RuntimeError):
                await websocket.close()


async def _authenticate_socket(websocket: WebSocket, token: str) -> AuthorizationPrincipal | None:
    token_service = getattr(websocket.app.state, "websocket_token_service", None)
    repository = getattr(websocket.app.state, "authorization_repository", None)
    if token_service is None or repository is None:
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR, reason="chat unavailable")
        return None
    try:
        user_id = await token_service.consume(token)
        principal = await repository.load_principal(user_id)
    except InvalidWebSocketToken:
        principal = None
    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return None
    return principal


async def _serve_request(
    websocket: WebSocket,
    principal: AuthorizationPrincipal,
    event: ChatRequestEventDTO,
    send,
    completed: dict[str, list[dict[str, Any]]],
) -> None:
    emitted: list[dict[str, Any]] = []

    async def emit(payload: dict[str, Any]) -> None:
        emitted.append(payload)
        await send(payload)

    try:
        runtime = getattr(websocket.app.state, "agent_runtime", None)
        if runtime is None:
            raise RuntimeError("chat runtime unavailable")
        scope = await _shared_retrieval_scope(
            websocket.app, principal, event.options.knowledge_base_ids
        )

        # --- True streaming: intercept generation tokens via a queue ---
        from app.agents.langchain_rag import SimpleRAGGenerator

        generator = getattr(runtime, "_generator", None)
        can_stream = isinstance(generator, SimpleRAGGenerator)

        if can_stream:
            token_queue: asyncio.Queue[str | None] = asyncio.Queue()
            loop = asyncio.get_running_loop()
            original_generator = generator

            class _StreamingProxy:
                """Wraps the real generator to push tokens into an asyncio queue."""

                def generate(self, query, chunks, history=""):
                    result = None
                    for tok, final in original_generator.stream_generate(query, chunks, history):
                        if tok:
                            loop.call_soon_threadsafe(token_queue.put_nowait, tok)
                        if final is not None:
                            result = final
                    loop.call_soon_threadsafe(token_queue.put_nowait, None)
                    return result

                def generate_general(self, query, history=""):
                    result = None
                    for tok, final in original_generator.stream_generate_general(query, history):
                        if tok:
                            loop.call_soon_threadsafe(token_queue.put_nowait, tok)
                        if final is not None:
                            result = final
                    loop.call_soon_threadsafe(token_queue.put_nowait, None)
                    return result

            runtime._generator = _StreamingProxy()
            try:
                run_task = asyncio.create_task(
                    runtime.run(
                        conversation_id=event.conversation_id,
                        owner_user_id=principal.user_id,
                        query=event.content,
                        retrieval_scope=scope,
                        request_id=event.request_id,
                        principal=principal,
                    )
                )
                # Stream tokens to the client as they arrive
                while True:
                    token = await token_queue.get()
                    if token is None:
                        break
                    await emit(
                        {"type": "chat.delta", "request_id": event.request_id, "delta": token}
                    )

                result = await run_task
            finally:
                runtime._generator = original_generator
        else:
            # Fallback: non-streaming path (mock runtimes or legacy generators)
            result = await runtime.run(
                conversation_id=event.conversation_id,
                owner_user_id=principal.user_id,
                query=event.content,
                retrieval_scope=scope,
                request_id=event.request_id,
                principal=principal,
            )
            intent = result.state.get("intent")
            if intent is not None:
                await emit(
                    {"type": "chat.route", "request_id": event.request_id, "route": str(intent)}
                )
            for part in _text_chunks(result.message.content):
                await emit({"type": "chat.delta", "request_id": event.request_id, "delta": part})

        if can_stream:
            intent = result.state.get("intent")
            if intent is not None:
                await emit(
                    {"type": "chat.route", "request_id": event.request_id, "route": str(intent)}
                )
        recommendation_event = _recommendation_event(result, event.request_id)
        if recommendation_event is not None:
            await emit(recommendation_event)
        if result.message.sources:
            await emit(
                {
                    "type": "chat.sources",
                    "request_id": event.request_id,
                    "sources": [_source_data(source) for source in result.message.sources],
                }
            )
        await emit(
            {
                "type": "chat.completed",
                "request_id": event.request_id,
                "message_id": str(result.message.id),
                "usage": _usage_data(result.message),
                "finish_reason": "stop",
            }
        )
        completed[event.request_id] = emitted
    except asyncio.CancelledError:
        with suppress(Exception):
            await send(
                {
                    "type": "chat.completed",
                    "request_id": event.request_id,
                    "message_id": None,
                    "usage": None,
                    "finish_reason": "cancelled",
                }
            )
        raise
    except ConversationNotFound:
        await send(
            _chat_error(
                "CONVERSATION_NOT_FOUND",
                "The conversation does not exist or is not accessible",
                False,
                event.request_id,
            )
        )
    except TimeoutError:
        await send(
            _chat_error("CHAT_TIMEOUT", "The chat request timed out", True, event.request_id)
        )
    except AppError as exc:
        await send(_chat_error(exc.code, exc.message, False, event.request_id))
    except Exception:
        logger.exception(
            "WebSocket chat request failed",
            extra={
                "request_id": event.request_id,
                "user_id": str(principal.user_id),
                "conversation_id": str(event.conversation_id),
            },
        )
        await send(
            _chat_error(
                "CHAT_STREAM_ERROR",
                "The chat service failed while streaming the response",
                True,
                event.request_id,
            )
        )


def _recommendation_event(result, request_id: str) -> dict[str, Any] | None:
    generation = getattr(result, "generation", None)
    if generation is None:
        return None
    # general_chat 是纯对话，不涉及商家推荐，不应展示"没有足够证据"兜底
    state = getattr(result, "state", None) or {}
    if state.get("intent") == ChatIntent.GENERAL_CHAT:
        return None
    structured = generation.structured
    if structured is not None and structured.response_type is GenerationMode.RECOMMENDATION:
        source_chunk_ids = {
            source.evidence_id: source.chunk_id
            for source in generation.sources
            if source.evidence_id is not None
        }
        recommendations = [
            {
                "merchant_id": item.merchant_id,
                "name": item.name,
                "category": item.category,
                "reason": item.reason,
                "distance_meter": item.distance_meter,
                "avg_price_cent": item.avg_price_cent,
                "rating": item.rating,
                "business_status": (
                    item.business_status.value if item.business_status is not None else None
                ),
                "data_updated_at": item.data_updated_at,
                "source_chunk_ids": [
                    source_chunk_ids[source_id]
                    for source_id in item.source_ids
                    if source_id in source_chunk_ids
                ],
                "tags": list(item.tags),
            }
            for item in structured.recommendations
        ]
        return {
            "type": "chat.recommendations",
            "request_id": request_id,
            "recommendations": recommendations,
            "fallback": {"triggered": False},
        }
    if generation.is_fallback:
        return {
            "type": "chat.recommendations",
            "request_id": request_id,
            "recommendations": [],
            "fallback": {
                "triggered": True,
                "reason": generation.fallback_reason,
            },
        }
    return None


def _chat_error(
    code: str, message: str, retryable: bool, request_id: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "chat.error",
        "code": code,
        "message": message,
        "retryable": retryable,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def _validation_error(exc: ValidationError) -> dict[str, Any]:
    field = ".".join(str(part) for part in exc.errors()[0]["loc"])
    return _chat_error("VALIDATION_ERROR", f"Invalid event field: {field}", False)
