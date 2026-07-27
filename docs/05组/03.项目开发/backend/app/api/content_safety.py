"""Sensitive-word administration and input/output detection endpoints."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.content_safety import (
    ContentDirection,
    ContentSafetyService,
    SensitiveMatchType,
    SensitiveRuleRecord,
    SensitiveRuleScope,
)
from app.core.api import get_request_id, success_response
from app.core.errors import AppError

router = APIRouter(tags=["content-safety"])


class SensitiveRuleCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    word: str = Field(min_length=1, max_length=200)
    scope: SensitiveRuleScope = SensitiveRuleScope.BOTH
    match_type: SensitiveMatchType = SensitiveMatchType.CONTAINS
    severity: str = Field(default="HIGH", pattern="^(?i:LOW|MEDIUM|HIGH)$")


class ContentCheckDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)
    direction: ContentDirection
    conversation_id: UUID | None = None


def get_content_safety_service(request: Request) -> ContentSafetyService:
    service: ContentSafetyService | None = getattr(
        request.app.state, "content_safety_service", None
    )
    if service is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "内容安全服务尚未配置")
    return service


ContentSafetyDependency = Annotated[ContentSafetyService, Depends(get_content_safety_service)]


def _require_platform_admin(principal: CurrentPrincipal) -> None:
    if not principal.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "仅平台管理员可以管理敏感词规则")


def _rule_data(rule: SensitiveRuleRecord) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "word": rule.word,
        "scope": rule.scope.value,
        "match_type": rule.match_type.value,
        "severity": rule.severity,
        "version_no": rule.version_no,
        "enabled": rule.enabled,
    }


@router.get("/sensitive-words")
async def list_sensitive_words(
    request: Request,
    principal: CurrentPrincipal,
    service: ContentSafetyDependency,
    enabled_only: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    _require_platform_admin(principal)
    rows = await service.list_rules(enabled_only=enabled_only)
    return success_response(request, {"items": [_rule_data(row) for row in rows]})


@router.post("/sensitive-words", status_code=201)
async def create_sensitive_word(
    request: Request,
    body: SensitiveRuleCreateDTO,
    principal: CurrentPrincipal,
    service: ContentSafetyDependency,
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        row = await service.create_rule(
            word=body.word,
            scope=body.scope,
            match_type=body.match_type,
            severity=body.severity,
            created_by=principal.user_id,
        )
    except ValueError as exc:
        raise AppError(422, "INVALID_SENSITIVE_RULE", str(exc)) from exc
    return success_response(request, _rule_data(row), message="created")


@router.delete("/sensitive-words/{rule_id}")
async def delete_sensitive_word(
    request: Request,
    rule_id: UUID,
    principal: CurrentPrincipal,
    service: ContentSafetyDependency,
) -> dict[str, Any]:
    _require_platform_admin(principal)
    row = await service.disable_rule(rule_id=rule_id)
    if row is None:
        raise AppError(404, "SENSITIVE_RULE_NOT_FOUND", "违禁词规则不存在")
    return success_response(request, _rule_data(row), message="deleted")


@router.post("/content-safety/check")
async def check_content(
    request: Request,
    body: ContentCheckDTO,
    principal: CurrentPrincipal,
    service: ContentSafetyDependency,
) -> dict[str, Any]:
    if body.conversation_id is not None:
        request.state.conversation_id = str(body.conversation_id)
    result = await service.check(
        content=body.content,
        direction=body.direction,
        actor_id=principal.user_id,
        request_id=get_request_id(request),
        conversation_id=body.conversation_id,
    )
    if not result.allowed:
        code = (
            "SENSITIVE_INPUT_REJECTED"
            if result.direction is ContentDirection.INPUT
            else "SENSITIVE_OUTPUT_STOPPED"
        )
        message = (
            "输入包含受限内容，已拒绝处理"
            if body.direction is ContentDirection.INPUT
            else "输出包含受限内容，已停止返回"
        )
        raise AppError(422, code, message)
    return success_response(
        request,
        {"allowed": True, "direction": result.direction.value, "decision": result.decision},
    )
