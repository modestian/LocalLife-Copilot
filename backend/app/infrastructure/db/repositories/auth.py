from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.auth import AuthUser
from app.infrastructure.db.models.identity import RefreshToken, User


class SQLAlchemyAuthRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def find_user(self, normalized_username: str) -> AuthUser | None:
        async with self._session_factory() as session:
            user = await session.scalar(
                select(User).where(User.normalized_username == normalized_username)
            )
            if user is None:
                return None
            return AuthUser(
                id=user.id,
                password_hash=user.password_hash,
                status=user.status,
                deleted_at=user.deleted_at,
            )

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> bool:
        async with self._session_factory() as session, session.begin():
            user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
            if user is None or user.status != "ACTIVE" or user.deleted_at is not None:
                return False
            user.last_login_at = authenticated_at
            user.login_failed_count = 0
            session.add(RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
            return True

    async def rotate_refresh_token(
        self,
        *,
        current_token_hash: str,
        replacement_token_hash: str,
        replacement_expires_at: datetime,
        rotated_at: datetime,
    ) -> UUID | None:
        async with self._session_factory() as session, session.begin():
            row = (
                await session.execute(
                    select(RefreshToken, User)
                    .join(User, User.id == RefreshToken.user_id)
                    .where(RefreshToken.token_hash == current_token_hash)
                    .with_for_update()
                )
            ).one_or_none()
            if row is None:
                return None
            current, user = row
            if (
                current.revoked_at is not None
                or current.expires_at <= rotated_at
                or user.status != "ACTIVE"
                or user.deleted_at is not None
            ):
                return None

            replacement = RefreshToken(
                user_id=user.id,
                token_hash=replacement_token_hash,
                expires_at=replacement_expires_at,
            )
            session.add(replacement)
            await session.flush()
            current.revoked_at = rotated_at
            current.replaced_by_id = replacement.id
            return user.id

    async def revoke_refresh_token(self, *, token_hash: str, revoked_at: datetime) -> bool:
        async with self._session_factory() as session, session.begin():
            current = await session.scalar(
                select(RefreshToken).where(RefreshToken.token_hash == token_hash).with_for_update()
            )
            if (
                current is None
                or current.revoked_at is not None
                or current.expires_at <= revoked_at
            ):
                return False
            current.revoked_at = revoked_at
            return True
