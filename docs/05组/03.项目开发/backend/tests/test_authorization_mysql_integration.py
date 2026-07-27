import os

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.authorization import ResourceType
from app.core.ids import uuid7
from app.core.security import PasswordService
from app.infrastructure.db.models.identity import (
    Permission,
    ResourceGrant,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.infrastructure.db.repositories.authorization import (
    SQLAlchemyAuthorizationRepository,
)


@pytest.mark.skipif(
    os.getenv("AUTH_MYSQL_INTEGRATION") != "1",
    reason="set AUTH_MYSQL_INTEGRATION=1 to run the MySQL authorization integration test",
)
@pytest.mark.asyncio
async def test_mysql_principal_combines_role_permissions_and_resource_grants() -> None:
    database_url = os.environ["AUTH_MYSQL_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = str(uuid7())
    user_id = uuid7()
    role_id = uuid7()
    disabled_role_id = uuid7()
    permission_id = uuid7()
    user_resource_id = uuid7()
    role_resource_id = uuid7()

    try:
        async with session_factory() as session, session.begin():
            session.add_all(
                [
                    User(
                        id=user_id,
                        username=f"authorization-integration-{suffix}",
                        normalized_username=f"authorization-integration-{suffix}",
                        password_hash=PasswordService().hash("integration-password"),
                        display_name="Authorization integration test",
                    ),
                    Role(
                        id=role_id,
                        code=f"KB_READER_{suffix}",
                        name="Knowledge base reader",
                    ),
                    Role(
                        id=disabled_role_id,
                        code=f"DISABLED_{suffix}",
                        name="Disabled role",
                        status="DISABLED",
                    ),
                    Permission(
                        id=permission_id,
                        code=f"kb.read.{suffix}",
                        resource_type="KNOWLEDGE_BASE",
                        action="READ",
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    UserRole(user_id=user_id, role_id=role_id),
                    UserRole(user_id=user_id, role_id=disabled_role_id),
                    RolePermission(role_id=role_id, permission_id=permission_id),
                    ResourceGrant(
                        subject_type="USER",
                        subject_id=user_id,
                        resource_type="KNOWLEDGE_BASE",
                        resource_id=user_resource_id,
                        action="READ",
                    ),
                    ResourceGrant(
                        subject_type="ROLE",
                        subject_id=role_id,
                        resource_type="KNOWLEDGE_BASE",
                        resource_id=role_resource_id,
                        action="READ",
                    ),
                    ResourceGrant(
                        subject_type="ROLE",
                        subject_id=disabled_role_id,
                        resource_type="KNOWLEDGE_BASE",
                        resource_id=uuid7(),
                        action="READ",
                    ),
                ]
            )

        repository = SQLAlchemyAuthorizationRepository(session_factory)
        principal = await repository.load_principal(user_id)

        assert principal is not None
        assert [role.code for role in principal.roles] == [f"KB_READER_{suffix}".upper()]
        assert [permission.code for permission in principal.permissions] == [f"kb.read.{suffix}"]
        assert principal.authorized_resource_ids(ResourceType.KNOWLEDGE_BASE, "READ") == {
            user_resource_id,
            role_resource_id,
        }

        async with session_factory() as session, session.begin():
            user = await session.get(User, user_id)
            assert user is not None
            user.status = "DISABLED"
        assert await repository.load_principal(user_id) is None
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(
                delete(ResourceGrant).where(
                    ResourceGrant.subject_id.in_([user_id, role_id, disabled_role_id])
                )
            )
            await session.execute(delete(User).where(User.id == user_id))
            await session.execute(delete(Role).where(Role.id.in_([role_id, disabled_role_id])))
            await session.execute(delete(Permission).where(Permission.id == permission_id))
        await engine.dispose()
