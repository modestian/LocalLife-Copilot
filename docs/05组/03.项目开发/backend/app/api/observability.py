"""Read-only audit and Prometheus observability endpoints."""

import ipaddress
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.audit import (
    AuditFilter,
    AuditQueryService,
    AuditRecord,
    ChatLogFilter,
    ChatLogQueryService,
    ChatLogRecord,
)
from app.core.api import success_response
from app.core.errors import AppError
from app.core.observability import MetricsRegistry, redact_sensitive_data

audit_router = APIRouter(tags=["audit"])
metrics_router = APIRouter(tags=["observability"])


def get_audit_service(request: Request) -> AuditQueryService:
    service: AuditQueryService | None = getattr(request.app.state, "audit_service", None)
    if service is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "审计查询服务尚未配置")
    return service


AuditServiceDependency = Annotated[AuditQueryService, Depends(get_audit_service)]


def get_chat_log_service(request: Request) -> ChatLogQueryService:
    service: ChatLogQueryService | None = getattr(request.app.state, "chat_log_service", None)
    if service is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "对话日志查询服务尚未配置")
    return service


ChatLogServiceDependency = Annotated[ChatLogQueryService, Depends(get_chat_log_service)]


def _serialize_audit(row: AuditRecord) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "actor_id": str(row.actor_id),
        "action": row.action,
        "module": row.resource_type,
        "resource_id": str(row.resource_id) if row.resource_id else None,
        "request_id": row.request_id,
        "ip_address": str(ipaddress.ip_address(row.ip_address)) if row.ip_address else None,
        "result": row.result,
        "before_summary": redact_sensitive_data(row.before_summary),
        "after_summary": redact_sensitive_data(row.after_summary),
        "created_at": row.created_at.isoformat(),
    }


def _serialize_chat_log(row: ChatLogRecord) -> dict[str, Any]:
    return {
        "message_id": str(row.message_id),
        "conversation_id": str(row.conversation_id),
        "user_id": str(row.user_id),
        "request_id": row.request_id,
        "role": row.role,
        "status": row.status,
        "model_version_id": str(row.model_version_id) if row.model_version_id else None,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "latency_ms": row.latency_ms,
        "error_code": row.error_code,
        "created_at": row.created_at.isoformat(),
    }


@audit_router.get("/audit-logs")
async def list_audit_logs(
    request: Request,
    principal: CurrentPrincipal,
    service: AuditServiceDependency,
    user_id: Annotated[UUID | None, Query()] = None,
    module: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    start_time: Annotated[datetime | None, Query()] = None,
    end_time: Annotated[datetime | None, Query()] = None,
    result: Annotated[Literal["SUCCEEDED", "FAILED", "BLOCKED"] | None, Query()] = None,
    cursor: Annotated[str | None, Query(max_length=1000)] = None,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    if not principal.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "仅平台管理员可以查询审计日志")
    try:
        page = await service.query(
            AuditFilter(
                actor_id=user_id,
                module=module,
                start_time=start_time,
                end_time=end_time,
                result=result,
            ),
            page_size=page_size,
            cursor=cursor,
        )
    except ValueError as exc:
        raise AppError(422, "INVALID_AUDIT_QUERY", str(exc)) from exc
    return success_response(
        request,
        {
            "items": [_serialize_audit(row) for row in page.items],
            "next_cursor": page.next_cursor,
            "page_size": page_size,
        },
    )


@audit_router.get("/chat-logs")
async def list_chat_logs(
    request: Request,
    principal: CurrentPrincipal,
    service: ChatLogServiceDependency,
    user_id: Annotated[UUID | None, Query()] = None,
    conversation_id: Annotated[UUID | None, Query()] = None,
    start_time: Annotated[datetime | None, Query()] = None,
    end_time: Annotated[datetime | None, Query()] = None,
    status: Annotated[
        Literal["STREAMING", "COMPLETED", "FAILED", "CANCELLED"] | None, Query()
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    if not principal.is_platform_admin:
        if user_id is not None and user_id != principal.user_id:
            raise AppError(403, "FORBIDDEN", "不能查询其他用户的对话日志")
        user_id = principal.user_id
    try:
        rows = await service.query(
            ChatLogFilter(
                user_id=user_id,
                conversation_id=conversation_id,
                start_time=start_time,
                end_time=end_time,
                status=status,
            ),
            page=page,
            page_size=page_size,
        )
    except ValueError as exc:
        raise AppError(422, "INVALID_CHAT_LOG_QUERY", str(exc)) from exc
    return success_response(
        request,
        {
            "items": [_serialize_chat_log(row) for row in rows],
            "page": page,
            "page_size": page_size,
        },
    )


@metrics_router.get("/metrics", include_in_schema=False)
async def metrics(request: Request) -> PlainTextResponse:
    if not _is_internal_metrics_client(request):
        raise AppError(403, "FORBIDDEN", "指标接口仅允许内网访问")
    registry: MetricsRegistry = request.app.state.metrics_registry
    return PlainTextResponse(
        registry.render_prometheus(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


def _is_internal_metrics_client(request: Request) -> bool:
    host = request.client.host if request.client else ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        settings = getattr(request.app.state, "settings", None)
        environment = getattr(settings, "app_environment", "production").lower()
        return environment not in {"production", "prod"}
    return address.is_private or address.is_loopback or address.is_link_local
