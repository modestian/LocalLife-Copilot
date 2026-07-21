from dataclasses import asdict
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.conversations import (
    ConversationNotFound,
    MessageInput,
    MessageNotFound,
    MessageRole,
    MessageStatus,
)
from app.core.api import success_response
from app.core.errors import AppError

router = APIRouter(prefix="/conversations", tags=["conversations"])


class ConversationCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, max_length=255)
    scenario: str | None = Field(default=None, max_length=64)
    constraints: dict[str, object] = Field(default_factory=dict)
    settings: dict[str, object] = Field(default_factory=dict)


class ConversationSettingsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int | None = Field(default=None, ge=1, le=100)
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    context_turns: int | None = Field(default=None, ge=1, le=50)


class MessageCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: MessageRole = MessageRole.USER
    content: str = Field(min_length=1, max_length=100000)
    request_id: str | None = Field(default=None, min_length=1, max_length=64)
    parent_message_id: UUID | None = None


class TruncateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: UUID


def _conversation_data(row) -> dict[str, Any]:
    settings = {key: value for key, value in row.settings.items() if not key.startswith("_")}
    return {
        "id": str(row.id),
        "owner_user_id": str(row.owner_user_id),
        "title": row.title or "",
        "scenario": settings.get("scenario"),
        "constraints": settings.get("constraints", {}),
        "settings": settings,
        "status": row.status.value,
        "memory_backend": row.memory_backend,
        "current_branch_message_id": (
            str(row.current_branch_message_id) if row.current_branch_message_id else None
        ),
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _message_data(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "parent_message_id": str(row.parent_message_id) if row.parent_message_id else None,
        "sequence_no": row.sequence_no,
        "request_id": row.request_id,
        "role": row.role.value,
        "content": row.content,
        "status": row.status.value,
        "created_at": row.created_at.isoformat(),
        "sources": [
            {
                **asdict(source),
                "chunk_id": str(source.chunk_id),
            }
            for source in row.sources
        ],
    }


def _repository(request: Request):
    return request.app.state.conversation_repository


async def _not_found(coro):
    try:
        return await coro
    except (ConversationNotFound, MessageNotFound) as exc:
        raise AppError(404, "NOT_FOUND", "会话或消息不存在") from exc


@router.post("")
async def create_conversation(
    request: Request, body: ConversationCreateDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    settings = {key: value for key, value in body.settings.items() if not key.startswith("_")}
    if body.scenario is not None:
        settings["scenario"] = body.scenario
    settings["constraints"] = body.constraints
    row = await _repository(request).create_conversation(
        principal.user_id, title=body.title, settings=settings
    )
    return success_response(request, _conversation_data(row))


@router.get("")
async def list_conversations(
    request: Request,
    principal: CurrentPrincipal,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    rows = await _repository(request).list_conversations(
        principal.user_id, limit=page_size, offset=(page - 1) * page_size
    )
    return success_response(
        request,
        {"items": [_conversation_data(row) for row in rows], "page": page, "page_size": page_size},
    )


@router.get("/{conversation_id}/messages")
async def list_messages(
    request: Request,
    conversation_id: UUID,
    principal: CurrentPrincipal,
    after_sequence: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    if after_sequence is None and limit <= 20:
        rows = await _not_found(
            request.app.state.conversation_memory.load(conversation_id, principal.user_id)
        )
        rows = rows[-limit:]
    else:
        rows = await _not_found(
            _repository(request).list_messages(
                conversation_id,
                principal.user_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        )
    return success_response(request, {"items": [_message_data(row) for row in rows]})


@router.post("/{conversation_id}/messages")
async def append_message(
    request: Request,
    conversation_id: UUID,
    body: MessageCreateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    row = await _not_found(
        _repository(request).append_message(
            conversation_id,
            principal.user_id,
            MessageInput(
                role=body.role,
                content=body.content,
                status=MessageStatus.COMPLETED,
                request_id=body.request_id,
                parent_message_id=body.parent_message_id,
            ),
        )
    )
    await request.app.state.conversation_memory.invalidate(conversation_id)
    return success_response(request, _message_data(row))


@router.patch("/{conversation_id}/settings")
async def update_settings(
    request: Request,
    conversation_id: UUID,
    body: ConversationSettingsDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    row = await _not_found(
        _repository(request).update_settings(
            conversation_id,
            principal.user_id,
            body.model_dump(exclude_none=True),
        )
    )
    return success_response(request, _conversation_data(row))


@router.post("/{conversation_id}/truncate")
async def truncate_conversation(
    request: Request,
    conversation_id: UUID,
    body: TruncateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    row = await _not_found(
        request.app.state.agent_memory.truncate(conversation_id, principal.user_id, body.message_id)
    )
    return success_response(request, _conversation_data(row))


@router.delete("/{conversation_id}")
async def delete_conversation(
    request: Request, conversation_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _not_found(_repository(request).delete_conversation(conversation_id, principal.user_id))
    await request.app.state.conversation_memory.invalidate(conversation_id)
    return success_response(request, {"id": str(conversation_id), "status": "DELETED"})
