from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

UserStatus = Literal["ACTIVE", "DISABLED", "LOCKED"]
RoleStatus = Literal["ACTIVE", "DISABLED"]
ResourceTypeValue = Literal["KNOWLEDGE_BASE", "MERCHANT", "REGION"]


class IdentityConflict(ValueError):
    pass


class IdentityNotFound(LookupError):
    pass


class IdentitySafetyViolation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceGrantInput:
    resource_type: ResourceTypeValue
    resource_id: UUID
    actions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UserCreateInput:
    username: str
    display_name: str
    password_hash: str
    email: str | None
    department_id: UUID | None
    role_ids: tuple[UUID, ...]
    resource_grants: tuple[ResourceGrantInput, ...]


@dataclass(frozen=True, slots=True)
class UserPatch:
    display_name: str | None = None
    email: str | None = None
    email_present: bool = False
    department_id: UUID | None = None
    department_present: bool = False
    status: UserStatus | None = None


@dataclass(frozen=True, slots=True)
class RoleCreateInput:
    code: str
    name: str
    permission_ids: tuple[UUID, ...]


class IdentityManagementRepository(Protocol):
    async def list_users(
        self, *, query: str | None, status: UserStatus | None, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]: ...

    async def create_user(
        self, value: UserCreateInput, *, actor_id: UUID, request_id: str
    ) -> dict[str, object]: ...

    async def update_user(
        self,
        user_id: UUID,
        patch: UserPatch,
        *,
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]: ...

    async def delete_user(self, user_id: UUID, *, actor_id: UUID, request_id: str) -> None: ...

    async def reset_password(
        self,
        user_id: UUID,
        password_hash: str,
        *,
        actor_id: UUID,
        request_id: str,
    ) -> None: ...

    async def replace_user_access(
        self,
        user_id: UUID,
        *,
        role_ids: tuple[UUID, ...],
        resource_grants: tuple[ResourceGrantInput, ...],
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]: ...

    async def list_roles(self) -> list[dict[str, object]]: ...

    async def create_role(
        self, value: RoleCreateInput, *, actor_id: UUID, request_id: str
    ) -> dict[str, object]: ...

    async def replace_role_permissions(
        self,
        role_id: UUID,
        permission_ids: tuple[UUID, ...],
        *,
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]: ...

    async def list_permissions(self) -> list[dict[str, object]]: ...


def normalize_username(value: str) -> str:
    return value.strip().casefold()


def normalize_email(value: str | None) -> str | None:
    return value.strip().casefold() if value and value.strip() else None
