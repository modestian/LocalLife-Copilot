from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.identity_management import (
    IdentityConflict,
    IdentityNotFound,
    IdentitySafetyViolation,
    ResourceGrantInput,
    RoleCreateInput,
    UserCreateInput,
    UserPatch,
    UserStatus,
    normalize_email,
    normalize_username,
)
from app.core.ids import uuid7
from app.infrastructure.db.models.governance import AuditLog
from app.infrastructure.db.models.identity import (
    Permission,
    RefreshToken,
    ResourceGrant,
    Role,
    RolePermission,
    User,
    UserRole,
)


class SQLAlchemyIdentityManagementRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list_users(
        self, *, query: str | None, status: UserStatus | None, limit: int, offset: int
    ) -> tuple[list[dict[str, object]], int]:
        conditions = [User.deleted_at.is_(None)]
        if status:
            conditions.append(User.status == status)
        if query:
            pattern = f"%{query.strip().casefold()}%"
            conditions.append(
                or_(
                    User.normalized_username.like(pattern),
                    func.lower(User.display_name).like(pattern),
                    User.normalized_email.like(pattern),
                )
            )
        async with self._session_factory() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
            )
            users = (
                await session.scalars(
                    select(User)
                    .where(*conditions)
                    .order_by(User.created_at.desc(), User.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [await self._user_payload(session, user) for user in users], total

    async def create_user(
        self, value: UserCreateInput, *, actor_id: UUID, request_id: str
    ) -> dict[str, object]:
        async with self._session_factory() as session, session.begin():
            await self._validate_roles(session, value.role_ids)
            user = User(
                id=uuid7(),
                username=value.username.strip(),
                normalized_username=normalize_username(value.username),
                email=value.email.strip() if value.email else None,
                normalized_email=normalize_email(value.email),
                password_hash=value.password_hash,
                display_name=value.display_name.strip(),
                department_id=value.department_id,
                status="ACTIVE",
            )
            session.add(user)
            try:
                await session.flush()
            except IntegrityError as exc:
                raise IdentityConflict("用户名或邮箱已存在") from exc
            await self._replace_access_rows(
                session, user.id, value.role_ids, value.resource_grants, actor_id
            )
            self._audit(
                session,
                actor_id=actor_id,
                action="USER_CREATE",
                resource_type="USER",
                resource_id=user.id,
                request_id=request_id,
                after={"username": user.username, "status": user.status},
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise IdentityConflict("用户名或邮箱已存在") from exc
            return await self._user_payload(session, user)

    async def update_user(
        self,
        user_id: UUID,
        patch: UserPatch,
        *,
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]:
        async with self._session_factory() as session, session.begin():
            user = await self._locked_user(session, user_id)
            before = {"display_name": user.display_name, "email": user.email, "status": user.status}
            if patch.status and patch.status != "ACTIVE":
                await self._protect_last_platform_admin(session, user_id)
            if patch.display_name is not None:
                user.display_name = patch.display_name.strip()
            if patch.email_present:
                user.email = patch.email.strip() if patch.email else None
                user.normalized_email = normalize_email(patch.email)
            if patch.department_present:
                user.department_id = patch.department_id
            if patch.status is not None:
                user.status = patch.status
                if patch.status != "ACTIVE":
                    await self._revoke_sessions(session, user)
            self._audit(
                session,
                actor_id=actor_id,
                action="USER_UPDATE",
                resource_type="USER",
                resource_id=user.id,
                request_id=request_id,
                before=before,
                after={
                    "display_name": user.display_name,
                    "email": user.email,
                    "status": user.status,
                },
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise IdentityConflict("邮箱已被其他账号使用") from exc
            return await self._user_payload(session, user)

    async def delete_user(self, user_id: UUID, *, actor_id: UUID, request_id: str) -> None:
        async with self._session_factory() as session, session.begin():
            user = await self._locked_user(session, user_id)
            await self._protect_last_platform_admin(session, user_id)
            user.deleted_at = datetime.now(UTC).replace(tzinfo=None)
            user.status = "DISABLED"
            await self._revoke_sessions(session, user)
            self._audit(
                session,
                actor_id=actor_id,
                action="USER_DELETE",
                resource_type="USER",
                resource_id=user.id,
                request_id=request_id,
                before={"username": user.username, "status": "ACTIVE"},
                after={"status": "DISABLED", "deleted": True},
            )

    async def reset_password(
        self,
        user_id: UUID,
        password_hash: str,
        *,
        actor_id: UUID,
        request_id: str,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            user = await self._locked_user(session, user_id)
            user.password_hash = password_hash
            await self._revoke_sessions(session, user)
            self._audit(
                session,
                actor_id=actor_id,
                action="USER_PASSWORD_RESET",
                resource_type="USER",
                resource_id=user.id,
                request_id=request_id,
                after={"sessions_revoked": True},
            )

    async def replace_user_access(
        self,
        user_id: UUID,
        *,
        role_ids: tuple[UUID, ...],
        resource_grants: tuple[ResourceGrantInput, ...],
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]:
        async with self._session_factory() as session, session.begin():
            user = await self._locked_user(session, user_id)
            await self._validate_roles(session, role_ids)
            current_codes = set(
                await session.scalars(
                    select(Role.code)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id)
                )
            )
            new_codes = set(await session.scalars(select(Role.code).where(Role.id.in_(role_ids))))
            if "PLATFORM_ADMIN" in current_codes and "PLATFORM_ADMIN" not in new_codes:
                await self._protect_last_platform_admin(session, user_id)
            await self._replace_access_rows(session, user_id, role_ids, resource_grants, actor_id)
            await self._revoke_sessions(session, user)
            self._audit(
                session,
                actor_id=actor_id,
                action="USER_ACCESS_REPLACE",
                resource_type="USER",
                resource_id=user.id,
                request_id=request_id,
                before={"role_codes": sorted(current_codes)},
                after={
                    "role_codes": sorted(new_codes),
                    "resource_grant_count": sum(len(item.actions) for item in resource_grants),
                },
            )
            await session.flush()
            return await self._user_payload(session, user)

    async def list_roles(self) -> list[dict[str, object]]:
        async with self._session_factory() as session:
            roles = (await session.scalars(select(Role).order_by(Role.code))).all()
            return [await self._role_payload(session, role) for role in roles]

    async def create_role(
        self, value: RoleCreateInput, *, actor_id: UUID, request_id: str
    ) -> dict[str, object]:
        async with self._session_factory() as session, session.begin():
            await self._validate_permissions(session, value.permission_ids)
            role = Role(
                id=uuid7(),
                code=value.code.strip().upper(),
                name=value.name.strip(),
                is_system=False,
                status="ACTIVE",
            )
            session.add(role)
            await session.flush()
            session.add_all(
                RolePermission(role_id=role.id, permission_id=permission_id)
                for permission_id in value.permission_ids
            )
            self._audit(
                session,
                actor_id=actor_id,
                action="ROLE_CREATE",
                resource_type="ROLE",
                resource_id=role.id,
                request_id=request_id,
                after={"code": role.code, "permission_count": len(value.permission_ids)},
            )
            try:
                await session.flush()
            except IntegrityError as exc:
                raise IdentityConflict("角色编码已存在") from exc
            return await self._role_payload(session, role)

    async def replace_role_permissions(
        self,
        role_id: UUID,
        permission_ids: tuple[UUID, ...],
        *,
        actor_id: UUID,
        request_id: str,
    ) -> dict[str, object]:
        async with self._session_factory() as session, session.begin():
            role = await session.scalar(select(Role).where(Role.id == role_id).with_for_update())
            if role is None:
                raise IdentityNotFound("角色不存在")
            await self._validate_permissions(session, permission_ids)
            before = list(
                await session.scalars(
                    select(Permission.code)
                    .join(RolePermission, RolePermission.permission_id == Permission.id)
                    .where(RolePermission.role_id == role_id)
                )
            )
            await session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
            session.add_all(
                RolePermission(role_id=role_id, permission_id=permission_id)
                for permission_id in permission_ids
            )
            self._audit(
                session,
                actor_id=actor_id,
                action="ROLE_PERMISSIONS_REPLACE",
                resource_type="ROLE",
                resource_id=role.id,
                request_id=request_id,
                before={"permissions": sorted(before)},
                after={"permission_count": len(permission_ids)},
            )
            await session.flush()
            return await self._role_payload(session, role)

    async def list_permissions(self) -> list[dict[str, object]]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(Permission).order_by(Permission.resource_type, Permission.action)
                )
            ).all()
            return [self._permission_payload(row) for row in rows]

    async def _user_payload(self, session: AsyncSession, user: User) -> dict[str, object]:
        roles = (
            await session.execute(
                select(Role.id, Role.code, Role.name)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == user.id)
                .order_by(Role.code)
            )
        ).all()
        grants = (
            await session.execute(
                select(ResourceGrant.resource_type, ResourceGrant.resource_id, ResourceGrant.action)
                .where(
                    ResourceGrant.subject_type == "USER",
                    ResourceGrant.subject_id == user.id,
                )
                .order_by(
                    ResourceGrant.resource_type,
                    ResourceGrant.resource_id,
                    ResourceGrant.action,
                )
            )
        ).all()
        grouped: dict[tuple[str, UUID], list[str]] = {}
        for row in grants:
            grouped.setdefault((row.resource_type, row.resource_id), []).append(row.action)
        return {
            "id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "email": user.email,
            "department_id": str(user.department_id) if user.department_id else None,
            "status": user.status,
            "roles": [{"id": str(row.id), "code": row.code, "name": row.name} for row in roles],
            "resource_scopes": [
                {
                    "resource_type": key[0],
                    "resource_id": str(key[1]),
                    "actions": sorted(actions),
                }
                for key, actions in grouped.items()
            ],
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "created_at": user.created_at.isoformat(),
            "updated_at": user.updated_at.isoformat(),
        }

    async def _role_payload(self, session: AsyncSession, role: Role) -> dict[str, object]:
        permissions = (
            await session.scalars(
                select(Permission)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
                .order_by(Permission.resource_type, Permission.action)
            )
        ).all()
        return {
            "id": str(role.id),
            "code": role.code,
            "name": role.name,
            "is_system": role.is_system,
            "status": role.status,
            "permissions": [self._permission_payload(row) for row in permissions],
        }

    @staticmethod
    def _permission_payload(row: Permission) -> dict[str, object]:
        return {
            "id": str(row.id),
            "code": row.code,
            "resource_type": row.resource_type,
            "action": row.action,
        }

    async def _replace_access_rows(
        self,
        session: AsyncSession,
        user_id: UUID,
        role_ids: tuple[UUID, ...],
        grants: tuple[ResourceGrantInput, ...],
        actor_id: UUID,
    ) -> None:
        await session.execute(delete(UserRole).where(UserRole.user_id == user_id))
        await session.execute(
            delete(ResourceGrant).where(
                ResourceGrant.subject_type == "USER",
                ResourceGrant.subject_id == user_id,
            )
        )
        session.add_all(
            UserRole(user_id=user_id, role_id=role_id, granted_by=actor_id) for role_id in role_ids
        )
        session.add_all(
            ResourceGrant(
                id=uuid7(),
                subject_type="USER",
                subject_id=user_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                action=action.strip().upper(),
            )
            for grant in grants
            for action in grant.actions
        )

    async def _validate_roles(self, session: AsyncSession, role_ids: tuple[UUID, ...]) -> None:
        found = set(
            await session.scalars(
                select(Role.id).where(Role.id.in_(role_ids), Role.status == "ACTIVE")
            )
        )
        if found != set(role_ids):
            raise IdentityNotFound("角色不存在或已停用")

    async def _validate_permissions(
        self, session: AsyncSession, permission_ids: tuple[UUID, ...]
    ) -> None:
        found = set(
            await session.scalars(select(Permission.id).where(Permission.id.in_(permission_ids)))
        )
        if found != set(permission_ids):
            raise IdentityNotFound("权限不存在")

    async def _locked_user(self, session: AsyncSession, user_id: UUID) -> User:
        user = await session.scalar(
            select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update()
        )
        if user is None:
            raise IdentityNotFound("用户不存在")
        return user

    async def _protect_last_platform_admin(self, session: AsyncSession, user_id: UUID) -> None:
        await session.scalar(select(Role.id).where(Role.code == "PLATFORM_ADMIN").with_for_update())
        target_is_admin = await session.scalar(
            select(UserRole.user_id)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id, Role.code == "PLATFORM_ADMIN")
        )
        if target_is_admin is None:
            return
        active_admin_count = int(
            await session.scalar(
                select(func.count(func.distinct(User.id)))
                .select_from(User)
                .join(UserRole, UserRole.user_id == User.id)
                .join(Role, Role.id == UserRole.role_id)
                .where(
                    Role.code == "PLATFORM_ADMIN",
                    User.status == "ACTIVE",
                    User.deleted_at.is_(None),
                )
            )
            or 0
        )
        if active_admin_count <= 1:
            raise IdentitySafetyViolation("不能停用、删除或移除最后一个平台管理员")

    @staticmethod
    async def _revoke_sessions(session: AsyncSession, user: User) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)
        user.access_tokens_valid_after = now
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    @staticmethod
    def _audit(
        session: AsyncSession,
        *,
        actor_id: UUID,
        action: str,
        resource_type: str,
        resource_id: UUID | None,
        request_id: str,
        before: dict[str, object] | None = None,
        after: dict[str, object] | None = None,
    ) -> None:
        session.add(
            AuditLog(
                id=uuid7(),
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id[:128],
                result="SUCCEEDED",
                before_summary_json=before,
                after_summary_json=after,
            )
        )
