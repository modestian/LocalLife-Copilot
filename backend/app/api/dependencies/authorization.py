from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.authorization import (
    AuthenticationRequired,
    AuthorizationDenied,
    AuthorizationPrincipal,
    AuthorizationService,
    ResourceScopeDenied,
    ResourceType,
    RolePermissionDenied,
)
from app.core.errors import AppError

bearer_scheme = HTTPBearer(auto_error=False)


def get_authorization_service(request: Request) -> AuthorizationService:
    return request.app.state.authorization_service


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[AuthorizationService, Depends(get_authorization_service)],
) -> AuthorizationPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _authentication_error("AUTH_REQUIRED", "需要登录")
    try:
        return await service.authenticate(credentials.credentials)
    except AuthenticationRequired as exc:
        raise _authentication_error("AUTH_INVALID_ACCESS_TOKEN", "访问令牌无效或已过期") from exc


CurrentPrincipal = Annotated[AuthorizationPrincipal, Depends(get_current_principal)]


def require_permission(
    resource_type: str, action: str
) -> Callable[[CurrentPrincipal], AuthorizationPrincipal]:
    async def dependency(principal: CurrentPrincipal) -> AuthorizationPrincipal:
        try:
            principal.require_permission(resource_type, action)
        except AuthorizationDenied as exc:
            raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc
        return principal

    return dependency


def require_resource_access(
    resource_type: ResourceType | str,
    action: str,
    *,
    path_parameter: str = "resource_id",
) -> Callable[..., AuthorizationPrincipal]:
    async def dependency(request: Request, principal: CurrentPrincipal) -> AuthorizationPrincipal:
        raw_resource_id = request.path_params.get(path_parameter)
        try:
            resource_id = UUID(str(raw_resource_id))
        except (TypeError, ValueError) as exc:
            raise AppError(
                422,
                "VALIDATION_ERROR",
                "资源 ID 格式无效",
                [{"field": f"path.{path_parameter}", "reason": "uuid_parsing"}],
            ) from exc
        try:
            principal.require_resource_access(resource_type, resource_id, action)
        except RolePermissionDenied as exc:
            raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc
        except ResourceScopeDenied as exc:
            raise AppError(404, "NOT_FOUND", "资源不存在或无访问权限") from exc
        return principal

    return dependency


def _authentication_error(code: str, message: str) -> AppError:
    return AppError(
        401,
        code,
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )
