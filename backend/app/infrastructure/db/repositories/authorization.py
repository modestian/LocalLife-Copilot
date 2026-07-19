from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.authorization import (
    AuthorizationPrincipal,
    PermissionRule,
    ResourceGrantRule,
    ResourceType,
    RoleInfo,
)
from app.core.ids import uuid7
from app.infrastructure.db.models.identity import (
    Permission,
    ResourceGrant,
    Role,
    RolePermission,
    User,
    UserRole,
)


class SQLAlchemyAuthorizationRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def load_principal(self, user_id: UUID) -> AuthorizationPrincipal | None:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(
                    User.id == user_id,
                    User.status == "ACTIVE",
                    User.deleted_at.is_(None),
                )
            )
            if user is None:
                return None

            role_rows = (
                await session.execute(
                    select(Role.id, Role.code, Role.name)
                    .join(UserRole, UserRole.role_id == Role.id)
                    .where(UserRole.user_id == user_id, Role.status == "ACTIVE")
                    .order_by(Role.code)
                )
            ).all()
            role_ids = [row.id for row in role_rows]

            permissions: tuple[PermissionRule, ...] = ()
            if role_ids:
                permission_rows = (
                    await session.execute(
                        select(
                            Permission.code,
                            Permission.resource_type,
                            Permission.action,
                        )
                        .join(
                            RolePermission,
                            RolePermission.permission_id == Permission.id,
                        )
                        .where(RolePermission.role_id.in_(role_ids))
                        .distinct()
                        .order_by(Permission.code)
                    )
                ).all()
                permissions = tuple(
                    PermissionRule(
                        code=row.code,
                        resource_type=row.resource_type.strip().upper(),
                        action=row.action.strip().upper(),
                    )
                    for row in permission_rows
                )

            subject_conditions = [
                and_(
                    ResourceGrant.subject_type == "USER",
                    ResourceGrant.subject_id == user_id,
                )
            ]
            if role_ids:
                subject_conditions.append(
                    and_(
                        ResourceGrant.subject_type == "ROLE",
                        ResourceGrant.subject_id.in_(role_ids),
                    )
                )
            grant_rows = (
                await session.execute(
                    select(
                        ResourceGrant.resource_type,
                        ResourceGrant.resource_id,
                        ResourceGrant.action,
                    )
                    .where(or_(*subject_conditions))
                    .distinct()
                )
            ).all()
            grants = tuple(
                sorted(
                    {
                        ResourceGrantRule(
                            resource_type=ResourceType(row.resource_type.strip().upper()),
                            resource_id=row.resource_id,
                            action=row.action.strip().upper(),
                        )
                        for row in grant_rows
                    }
                )
            )

            return AuthorizationPrincipal(
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                email=user.email,
                department_id=user.department_id,
                roles=tuple(
                    RoleInfo(code=row.code.strip().upper(), name=row.name) for row in role_rows
                ),
                permissions=permissions,
                resource_grants=grants,
            )

    async def grant_user_resource(
        self,
        *,
        user_id: UUID,
        resource_type: ResourceType,
        resource_id: UUID,
        actions: tuple[str, ...] = ("READ", "UPDATE", "DELETE"),
    ) -> None:
        async with self._session_factory() as session, session.begin():
            for action in actions:
                normalized_action = action.strip().upper()
                existing = await session.scalar(
                    select(ResourceGrant.id).where(
                        ResourceGrant.subject_type == "USER",
                        ResourceGrant.subject_id == user_id,
                        ResourceGrant.resource_type == resource_type.value,
                        ResourceGrant.resource_id == resource_id,
                        ResourceGrant.action == normalized_action,
                    )
                )
                if existing is None:
                    session.add(
                        ResourceGrant(
                            id=uuid7(),
                            subject_type="USER",
                            subject_id=user_id,
                            resource_type=resource_type.value,
                            resource_id=resource_id,
                            action=normalized_action,
                        )
                    )
