import os
from datetime import timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.auth import AuthenticationError, AuthService
from app.application.authorization import AuthenticationRequired, AuthorizationService
from app.core.ids import uuid7
from app.core.security import AccessTokenService, PasswordService, RefreshTokenService
from app.infrastructure.db.models.identity import RefreshToken, User
from app.infrastructure.db.repositories.auth import SQLAlchemyAuthRepository
from app.infrastructure.db.repositories.authorization import SQLAlchemyAuthorizationRepository


@pytest.mark.skipif(
    os.getenv("AUTH_MYSQL_INTEGRATION") != "1",
    reason="set AUTH_MYSQL_INTEGRATION=1 to run the MySQL authentication integration test",
)
@pytest.mark.asyncio
async def test_mysql_refresh_rotation_and_revocation_are_persisted() -> None:
    database_url = os.environ["AUTH_MYSQL_DATABASE_URL"]
    engine = create_async_engine(database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    password_service = PasswordService()
    user_id = uuid7()
    username = f"auth-integration-{user_id}"

    try:
        async with session_factory() as session, session.begin():
            session.add(
                User(
                    id=user_id,
                    username=username,
                    normalized_username=username,
                    password_hash=password_service.hash("integration-password"),
                    display_name="Auth integration test",
                )
            )

        access_tokens = AccessTokenService(
            secret_key="integration-secret-key-with-at-least-32-bytes",
            issuer="integration-issuer",
            audience="integration-audience",
            ttl=timedelta(minutes=30),
        )
        service = AuthService(
            SQLAlchemyAuthRepository(session_factory),
            password_service,
            access_tokens,
            refresh_ttl=timedelta(days=7),
        )
        authorization = AuthorizationService(
            SQLAlchemyAuthorizationRepository(session_factory), access_tokens
        )

        original = await service.login(username, "integration-password")
        original_hash = RefreshTokenService.digest(original.refresh_token)
        async with session_factory() as session:
            stored_original = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == original_hash)
            )
            assert stored_original is not None
            assert stored_original.token_hash != original.refresh_token
            assert stored_original.revoked_at is None

        replacement = await service.refresh(original.refresh_token)
        assert (await authorization.authenticate(replacement.access_token)).user_id == user_id
        with pytest.raises(AuthenticationError):
            await service.refresh(original.refresh_token)

        async with session_factory() as session:
            stored_original = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == original_hash)
            )
            assert stored_original is not None
            assert stored_original.revoked_at is not None
            assert stored_original.replaced_by_id is not None

        await service.logout(replacement.refresh_token)
        async with session_factory() as session:
            stored_replacement = await session.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == RefreshTokenService.digest(replacement.refresh_token)
                )
            )
            assert stored_replacement is not None
            assert stored_replacement.revoked_at is not None
            stored_user = await session.get(User, user_id)
            assert stored_user is not None
            assert stored_user.access_tokens_valid_after is not None
        with pytest.raises(AuthenticationRequired, match="revoked access token"):
            await authorization.authenticate(replacement.access_token)
    finally:
        async with session_factory() as session, session.begin():
            await session.execute(delete(User).where(User.id == user_id))
        await engine.dispose()
