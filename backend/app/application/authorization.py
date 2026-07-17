from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, TypeVar
from uuid import UUID

from app.core.security import AccessTokenService, InvalidAccessTokenError


class ResourceType(StrEnum):
    KNOWLEDGE_BASE = "KNOWLEDGE_BASE"
    MERCHANT = "MERCHANT"
    REGION = "REGION"


class AuthenticationRequired(ValueError):
    """The access token is absent, invalid, or belongs to an inactive user."""


class AuthorizationDenied(PermissionError):
    """The authenticated principal lacks a role permission or resource grant."""


class RolePermissionDenied(AuthorizationDenied):
    """The principal lacks the RBAC permission required for an operation."""


class ResourceScopeDenied(AuthorizationDenied):
    """The requested resource is outside the principal's granted scope."""


@dataclass(frozen=True, slots=True, order=True)
class RoleInfo:
    code: str
    name: str


@dataclass(frozen=True, slots=True, order=True)
class PermissionRule:
    code: str
    resource_type: str
    action: str

    def matches(self, resource_type: str, action: str) -> bool:
        requested_type = _normalize(resource_type)
        requested_action = _normalize(action)
        return self.resource_type in {"*", requested_type} and self.action in {
            "*",
            requested_action,
        }


@dataclass(frozen=True, slots=True, order=True)
class ResourceGrantRule:
    resource_type: ResourceType
    resource_id: UUID
    action: str

    def matches(self, resource_type: ResourceType, resource_id: UUID, action: str) -> bool:
        return (
            self.resource_type == resource_type
            and self.resource_id == resource_id
            and self.action in {"*", _normalize(action)}
        )


@dataclass(frozen=True, slots=True)
class AuthorizationPrincipal:
    user_id: UUID
    username: str
    display_name: str
    email: str | None
    department_id: UUID | None
    roles: tuple[RoleInfo, ...]
    permissions: tuple[PermissionRule, ...]
    resource_grants: tuple[ResourceGrantRule, ...]

    @property
    def is_platform_admin(self) -> bool:
        return any(role.code == "PLATFORM_ADMIN" for role in self.roles)

    def has_permission(self, resource_type: str, action: str) -> bool:
        return self.is_platform_admin or any(
            permission.matches(resource_type, action) for permission in self.permissions
        )

    def require_permission(self, resource_type: str, action: str) -> None:
        if not self.has_permission(resource_type, action):
            raise RolePermissionDenied("role permission denied")

    def authorized_resource_ids(
        self, resource_type: ResourceType | str, action: str
    ) -> frozenset[UUID] | None:
        normalized_type = _resource_type(resource_type)
        self.require_permission(normalized_type.value, action)
        if self.is_platform_admin:
            return None
        return frozenset(
            grant.resource_id
            for grant in self.resource_grants
            if grant.resource_type == normalized_type and grant.action in {"*", _normalize(action)}
        )

    def require_resource_access(
        self,
        resource_type: ResourceType | str,
        resource_id: UUID,
        action: str,
    ) -> None:
        allowed_ids = self.authorized_resource_ids(resource_type, action)
        if allowed_ids is not None and resource_id not in allowed_ids:
            raise ResourceScopeDenied("resource scope denied")


class AuthorizationRepository(Protocol):
    async def load_principal(self, user_id: UUID) -> AuthorizationPrincipal | None: ...


class AuthorizationService:
    def __init__(
        self,
        repository: AuthorizationRepository,
        access_tokens: AccessTokenService,
    ) -> None:
        self._repository = repository
        self._access_tokens = access_tokens

    async def authenticate(self, access_token: str) -> AuthorizationPrincipal:
        try:
            claims = self._access_tokens.decode(access_token)
        except InvalidAccessTokenError as exc:
            raise AuthenticationRequired("invalid access token") from exc
        principal = await self._repository.load_principal(claims.user_id)
        if principal is None:
            raise AuthenticationRequired("inactive or missing user")
        return principal


T = TypeVar("T")


def filter_authorized_resources(
    principal: AuthorizationPrincipal,
    resources: list[T],
    *,
    resource_type: ResourceType | str,
    action: str,
    id_getter: Callable[[T], UUID],
) -> list[T]:
    allowed_ids = principal.authorized_resource_ids(resource_type, action)
    if allowed_ids is None:
        return resources
    return [resource for resource in resources if id_getter(resource) in allowed_ids]


def _normalize(value: str) -> str:
    normalized = value.strip().upper()
    if not normalized:
        raise ValueError("authorization value must not be empty")
    return normalized


def _resource_type(value: ResourceType | str) -> ResourceType:
    if isinstance(value, ResourceType):
        return value
    return ResourceType(_normalize(value))
