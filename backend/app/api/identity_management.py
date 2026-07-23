from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import AuthorizationPrincipal
from app.application.identity_management import (
    IdentityConflict,
    IdentityManagementRepository,
    IdentityNotFound,
    IdentitySafetyViolation,
    ResourceGrantInput,
    RoleCreateInput,
    UserCreateInput,
    UserPatch,
)
from app.core.api import success_response
from app.core.errors import AppError
from app.core.security import PasswordService

router = APIRouter(tags=["identity-management"])


class ResourceGrantDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: Literal["KNOWLEDGE_BASE", "MERCHANT", "REGION"]
    resource_id: UUID
    actions: list[str] = Field(min_length=1, max_length=8)

    @field_validator("actions")
    @classmethod
    def normalize_actions(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip().upper() for value in values if value.strip()))
        if not normalized:
            raise ValueError("至少需要一个资源操作")
        if any(len(value) > 32 for value in normalized):
            raise ValueError("资源操作长度不能超过 32")
        return normalized


class UserCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    display_name: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=12, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    department_id: UUID | None = None
    role_ids: list[UUID] = Field(min_length=1, max_length=16)
    resource_grants: list[ResourceGrantDTO] = Field(default_factory=list, max_length=100)


class UserPatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=254)
    department_id: UUID | None = None
    status: Literal["ACTIVE", "DISABLED", "LOCKED"] | None = None


class PasswordResetDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=12, max_length=128)


class UserAccessDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_ids: list[UUID] = Field(min_length=1, max_length=16)
    resource_grants: list[ResourceGrantDTO] = Field(default_factory=list, max_length=100)


class RoleCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    name: str = Field(min_length=1, max_length=128)
    permission_ids: list[UUID] = Field(default_factory=list, max_length=100)


class RolePermissionsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permission_ids: list[UUID] = Field(default_factory=list, max_length=100)


def _repository(request: Request) -> IdentityManagementRepository:
    return request.app.state.identity_management_repository


def _require_platform_admin(principal: AuthorizationPrincipal) -> None:
    if not principal.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "仅平台管理员可以管理账号与权限")


def _request_id(request: Request) -> str:
    return str(
        getattr(request.state, "request_id", None)
        or request.headers.get("X-Request-ID")
        or "identity-management"
    )


def _grants(values: list[ResourceGrantDTO]) -> tuple[ResourceGrantInput, ...]:
    grouped: dict[tuple[str, UUID], set[str]] = {}
    for value in values:
        grouped.setdefault((value.resource_type, value.resource_id), set()).update(value.actions)
    return tuple(
        ResourceGrantInput(resource_type=key[0], resource_id=key[1], actions=tuple(sorted(actions)))
        for key, actions in grouped.items()
    )


def _handle_error(exc: Exception) -> AppError:
    if isinstance(exc, IdentityNotFound):
        return AppError(404, "NOT_FOUND", str(exc))
    if isinstance(exc, IdentityConflict):
        return AppError(409, "IDENTITY_CONFLICT", str(exc))
    if isinstance(exc, IdentitySafetyViolation):
        return AppError(409, "IDENTITY_SAFETY_VIOLATION", str(exc))
    return AppError(400, "INVALID_IDENTITY_OPERATION", str(exc))


@router.get("/users")
async def list_users(
    request: Request,
    principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    query: Annotated[str | None, Query(max_length=128)] = None,
    status: Annotated[Literal["ACTIVE", "DISABLED", "LOCKED"] | None, Query()] = None,
) -> dict[str, Any]:
    _require_platform_admin(principal)
    items, total = await _repository(request).list_users(
        query=query, status=status, limit=page_size, offset=(page - 1) * page_size
    )
    return success_response(
        request,
        {"items": items, "total": total, "page": page, "page_size": page_size},
    )


@router.post("/users", status_code=201)
async def create_user(
    request: Request, body: UserCreateDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        created = await _repository(request).create_user(
            UserCreateInput(
                username=body.username,
                display_name=body.display_name,
                password_hash=PasswordService().hash(body.password),
                email=body.email,
                department_id=body.department_id,
                role_ids=tuple(dict.fromkeys(body.role_ids)),
                resource_grants=_grants(body.resource_grants),
            ),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except (IdentityConflict, IdentityNotFound, IdentitySafetyViolation, ValueError) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, created)


@router.patch("/users/{user_id}")
async def update_user(
    request: Request, user_id: UUID, body: UserPatchDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    if user_id == principal.user_id and body.status in {"DISABLED", "LOCKED"}:
        raise AppError(409, "SELF_LOCKOUT_FORBIDDEN", "不能停用或锁定当前登录账号")
    fields = body.model_fields_set
    try:
        updated = await _repository(request).update_user(
            user_id,
            UserPatch(
                display_name=body.display_name,
                email=body.email,
                email_present="email" in fields,
                department_id=body.department_id,
                department_present="department_id" in fields,
                status=body.status,
            ),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except (IdentityConflict, IdentityNotFound, IdentitySafetyViolation, ValueError) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, updated)


@router.delete("/users/{user_id}")
async def delete_user(
    request: Request, user_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    if user_id == principal.user_id:
        raise AppError(409, "SELF_DELETE_FORBIDDEN", "不能删除当前登录账号")
    try:
        await _repository(request).delete_user(
            user_id, actor_id=principal.user_id, request_id=_request_id(request)
        )
    except (IdentityNotFound, IdentitySafetyViolation) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, {"id": str(user_id), "status": "DELETED"})


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    request: Request, user_id: UUID, body: PasswordResetDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        await _repository(request).reset_password(
            user_id,
            PasswordService().hash(body.password),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except IdentityNotFound as exc:
        raise _handle_error(exc) from exc
    return success_response(request, {"id": str(user_id), "sessions_revoked": True})


@router.put("/users/{user_id}/roles")
async def replace_user_access(
    request: Request, user_id: UUID, body: UserAccessDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        updated = await _repository(request).replace_user_access(
            user_id,
            role_ids=tuple(dict.fromkeys(body.role_ids)),
            resource_grants=_grants(body.resource_grants),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except (IdentityNotFound, IdentitySafetyViolation, ValueError) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, updated)


@router.get("/roles")
async def list_roles(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    _require_platform_admin(principal)
    return success_response(request, {"items": await _repository(request).list_roles()})


@router.post("/roles", status_code=201)
async def create_role(
    request: Request, body: RoleCreateDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        created = await _repository(request).create_role(
            RoleCreateInput(
                code=body.code,
                name=body.name,
                permission_ids=tuple(dict.fromkeys(body.permission_ids)),
            ),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except (IdentityConflict, IdentityNotFound, ValueError) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, created)


@router.put("/roles/{role_id}/permissions")
async def replace_role_permissions(
    request: Request,
    role_id: UUID,
    body: RolePermissionsDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_platform_admin(principal)
    try:
        updated = await _repository(request).replace_role_permissions(
            role_id,
            tuple(dict.fromkeys(body.permission_ids)),
            actor_id=principal.user_id,
            request_id=_request_id(request),
        )
    except (IdentityNotFound, ValueError) as exc:
        raise _handle_error(exc) from exc
    return success_response(request, updated)


@router.get("/permissions")
async def list_permissions(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    _require_platform_admin(principal)
    return success_response(request, {"items": await _repository(request).list_permissions()})
