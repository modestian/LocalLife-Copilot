"""OpenAI-compatible Chat Completions transport."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from typing import Any, Literal, Self
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.contracts import RetrievalScope
from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import AuthorizationDenied, AuthorizationPrincipal
from app.application.chat_knowledge import (
    SharedChatKnowledgeDenied,
    SharedChatKnowledgeUnavailable,
)
from app.application.conversations import (
    ConversationNotFound,
    MessageInput,
    MessageRole,
    MessageStatus,
)
from app.core.api import get_request_id
from app.core.errors import AppError
from app.infrastructure.search.scope import scope_from_principal

router = APIRouter(prefix="/v1", tags=["openai-compatible"])
SUPPORTED_MODEL = "local-life-assistant"


class ChatMessageDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    role: Literal["system", "user", "assistant", "tool"]
    content: str = Field(min_length=1, max_length=100000)


class RetrievalDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")
    top_k: int = Field(default=8, ge=1, le=100)
    score_threshold: float = Field(default=0.35, ge=0, le=1)


class ChatCompletionRequestDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model: str = Field(min_length=1, max_length=200)
    messages: list[ChatMessageDTO] = Field(min_length=1, max_length=200)
    conversation_id: UUID | None = None
    stream: bool = False
    knowledge_base_ids: list[UUID] = Field(default_factory=list, max_length=50)
    retrieval: RetrievalDTO = Field(default_factory=RetrievalDTO)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=32768)

    @model_validator(mode="after")
    def require_final_user_message(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("the final message must have role 'user'")
        return self


@router.post("/chat/completions", response_model=None)
async def create_chat_completion(
    request: Request,
    body: ChatCompletionRequestDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any] | StreamingResponse:
    """Run one turn and return a parseable ``chat.completion`` object."""
    if body.model != SUPPORTED_MODEL:
        raise AppError(
            404,
            "MODEL_NOT_FOUND",
            f"The model '{body.model}' does not exist or is not available",
            [{"field": "model", "reason": "not_found"}],
        )

    repository = getattr(request.app.state, "conversation_repository", None)
    runtime = getattr(request.app.state, "agent_runtime", None)
    if repository is None or runtime is None:
        raise AppError(503, "CHAT_RUNTIME_UNAVAILABLE", "The chat service is unavailable")

    conversation_id = body.conversation_id
    if conversation_id is None:
        conversation = await repository.create_conversation(
            principal.user_id, settings={"constraints": {}}
        )
        conversation_id = conversation.id
        await _seed_history(request, conversation_id, principal.user_id, body.messages[:-1])

    scope = await _shared_retrieval_scope(request.app, principal, body.knowledge_base_ids)
    if body.stream:
        return StreamingResponse(
            _stream_completion(
                request=request,
                runtime=runtime,
                conversation_id=conversation_id,
                owner_user_id=principal.user_id,
                query=body.messages[-1].content,
                retrieval_scope=scope,
                request_id=get_request_id(request),
                model=body.model,
                principal=principal,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    try:
        result = await runtime.run(
            conversation_id=conversation_id,
            owner_user_id=principal.user_id,
            query=body.messages[-1].content,
            retrieval_scope=scope,
            request_id=get_request_id(request),
            principal=principal,
        )
    except ConversationNotFound as exc:
        raise AppError(
            404,
            "CONVERSATION_NOT_FOUND",
            "The conversation does not exist or is not accessible",
            [{"field": "conversation_id", "reason": "not_found"}],
        ) from exc
    except TimeoutError as exc:
        raise AppError(504, "CHAT_TIMEOUT", "The chat request timed out") from exc

    return _completion_data(result.message, conversation_id, body.model)


async def _stream_completion(
    *,
    request: Request,
    runtime,
    conversation_id: UUID,
    owner_user_id: UUID,
    query: str,
    retrieval_scope: RetrievalScope,
    request_id: str,
    model: str,
    principal: AuthorizationPrincipal,
):
    """Emit OpenAI-compatible chunks and always cancel unfinished downstream work."""
    stream_id = f"chatcmpl-{request_id}"
    yield _sse_data(
        _chunk_data(
            stream_id=stream_id,
            model=model,
            conversation_id=conversation_id,
            delta={"role": "assistant", "content": ""},
        )
    )
    task = asyncio.create_task(
        runtime.run(
            conversation_id=conversation_id,
            owner_user_id=owner_user_id,
            query=query,
            retrieval_scope=retrieval_scope,
            request_id=request_id,
            principal=principal,
        )
    )
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                return
            await asyncio.wait({task}, timeout=0.1)
        result = task.result()
        message = result.message
        for part in _text_chunks(message.content):
            yield _sse_data(
                _chunk_data(
                    stream_id=stream_id,
                    model=model,
                    conversation_id=conversation_id,
                    delta={"content": part},
                )
            )
        yield _sse_data(
            _chunk_data(
                stream_id=stream_id,
                model=model,
                conversation_id=conversation_id,
                delta={},
                finish_reason="stop",
                metadata={
                    "message_id": str(message.id),
                    "sources": [_source_data(source) for source in message.sources],
                    "usage": _usage_data(message),
                },
            )
        )
        yield "data: [DONE]\n\n"
    except asyncio.CancelledError:
        task.cancel()
        raise
    except Exception as exc:
        yield _sse_data({"error": _stream_error(exc)})
        yield "data: [DONE]\n\n"
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


def _chunk_data(
    *,
    stream_id: str,
    model: str,
    conversation_id: UUID,
    delta: dict[str, str],
    finish_reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": stream_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        "conversation_id": str(conversation_id),
    }
    if metadata is not None:
        data["metadata"] = metadata
    return data


def _sse_data(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _text_chunks(content: str, size: int = 64):
    for offset in range(0, len(content), size):
        yield content[offset : offset + size]


def _usage_data(message) -> dict[str, int]:
    prompt_tokens = message.prompt_tokens or 0
    completion_tokens = message.completion_tokens or 0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }


def _stream_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ConversationNotFound):
        return {
            "message": "The conversation does not exist or is not accessible",
            "type": "invalid_request_error",
            "param": "conversation_id",
            "code": "conversation_not_found",
        }
    if isinstance(exc, TimeoutError):
        return {
            "message": "The chat request timed out",
            "type": "server_error",
            "param": None,
            "code": "chat_timeout",
        }
    return {
        "message": "The chat service failed while streaming the response",
        "type": "server_error",
        "param": None,
        "code": "chat_stream_error",
    }


def _completion_data(message, conversation_id: UUID, model: str) -> dict[str, Any]:
    prompt_tokens = message.prompt_tokens or 0
    completion_tokens = message.completion_tokens or 0
    return {
        "id": f"chatcmpl-{message.id}",
        "object": "chat.completion",
        "created": int(message.created_at.timestamp()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": message.content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "conversation_id": str(conversation_id),
        "message_id": str(message.id),
        "sources": [_source_data(source) for source in message.sources],
    }


def _retrieval_scope(principal, knowledge_base_ids: list[UUID]) -> RetrievalScope:
    if not knowledge_base_ids:
        tenant_id = principal.department_id or principal.user_id
        return RetrievalScope(str(tenant_id), frozenset(), frozenset())
    if principal.department_id is None:
        raise AppError(403, "TENANT_CONTEXT_REQUIRED", "A tenant context is required")
    try:
        trusted = scope_from_principal(
            principal,
            tenant_id=principal.department_id,
            requested_knowledge_base_ids=knowledge_base_ids,
        )
    except AuthorizationDenied as exc:
        raise AppError(403, "FORBIDDEN", "Knowledge base access is denied") from exc
    if len(trusted.knowledge_base_ids) != len(set(knowledge_base_ids)):
        raise AppError(403, "FORBIDDEN", "Knowledge base access is denied")
    return RetrievalScope(
        trusted.tenant_id,
        trusted.knowledge_base_ids,
        trusted.resource_scopes,
    )


async def _shared_retrieval_scope(app, principal, knowledge_base_ids: list[UUID]) -> RetrievalScope:
    resolver = getattr(app.state, "shared_chat_knowledge_scope", None)
    if resolver is None:
        # Lightweight transport tests intentionally do not start database-backed
        # application services, so retain the pure authorization fallback there.
        return _retrieval_scope(principal, knowledge_base_ids)
    try:
        return await resolver.resolve(knowledge_base_ids)
    except SharedChatKnowledgeDenied as exc:
        raise AppError(
            403,
            "PUBLIC_KNOWLEDGE_SCOPE_DENIED",
            "The requested knowledge base is not available for public chat",
        ) from exc
    except SharedChatKnowledgeUnavailable as exc:
        raise AppError(
            503,
            "PUBLIC_KNOWLEDGE_UNAVAILABLE",
            "The public chat knowledge base is unavailable",
        ) from exc


async def _seed_history(
    request: Request,
    conversation_id: UUID,
    owner_user_id: UUID,
    messages: list[ChatMessageDTO],
) -> None:
    repository = request.app.state.conversation_repository
    for message in messages:
        await repository.append_message(
            conversation_id,
            owner_user_id,
            MessageInput(
                role=MessageRole(message.role.upper()),
                content=message.content,
                status=MessageStatus.COMPLETED,
            ),
        )
    memory = getattr(request.app.state, "conversation_memory", None)
    if messages and memory is not None:
        await memory.invalidate(conversation_id)


def _source_data(source) -> dict[str, Any]:
    chunk_id = str(source.chunk_id)
    return {
        "chunk_id": chunk_id,
        "source_location": source.source_location_snapshot,
        "source_url": f"/app/chunks/{quote(chunk_id, safe='')}",
        "content": source.content_snapshot,
        "score": source.score,
    }
