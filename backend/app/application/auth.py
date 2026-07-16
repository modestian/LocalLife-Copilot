from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.core.security import AccessTokenService, PasswordService, RefreshTokenService


class AuthenticationError(ValueError):
    """A deliberately non-specific authentication failure."""


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    password_hash: str
    status: str
    deleted_at: datetime | None = None

    @property
    def can_authenticate(self) -> bool:
        return self.status == "ACTIVE" and self.deleted_at is None


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime


class AuthRepository(Protocol):
    async def find_user(self, normalized_username: str) -> AuthUser | None: ...

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> bool: ...

    async def rotate_refresh_token(
        self,
        *,
        current_token_hash: str,
        replacement_token_hash: str,
        replacement_expires_at: datetime,
        rotated_at: datetime,
    ) -> UUID | None: ...

    async def revoke_refresh_token(self, *, token_hash: str, revoked_at: datetime) -> bool: ...


class AuthService:
    def __init__(
        self,
        repository: AuthRepository,
        password_service: PasswordService,
        access_tokens: AccessTokenService,
        *,
        refresh_ttl: timedelta,
    ) -> None:
        if refresh_ttl <= timedelta(0):
            raise ValueError("refresh token ttl must be positive")
        self._repository = repository
        self._passwords = password_service
        self._access_tokens = access_tokens
        self._refresh_ttl = refresh_ttl

    async def login(self, username: str, password: str) -> TokenPair:
        user = await self._repository.find_user(_normalize_username(username))
        if user is None:
            self._passwords.verify_dummy(password)
            raise AuthenticationError("invalid credentials")
        if not self._passwords.verify(user.password_hash, password) or not user.can_authenticate:
            raise AuthenticationError("invalid credentials")

        now = datetime.now(UTC)
        pair = self._build_pair(user.id, now)
        created = await self._repository.create_refresh_token(
            user_id=user.id,
            token_hash=RefreshTokenService.digest(pair.refresh_token),
            expires_at=_naive_utc(pair.refresh_expires_at),
            authenticated_at=_naive_utc(now),
        )
        if not created:
            raise AuthenticationError("invalid credentials")
        return pair

    async def refresh(self, refresh_token: str) -> TokenPair:
        _validate_refresh_token_shape(refresh_token)
        now = datetime.now(UTC)
        replacement = RefreshTokenService.generate()
        replacement_expires_at = now + self._refresh_ttl
        user_id = await self._repository.rotate_refresh_token(
            current_token_hash=RefreshTokenService.digest(refresh_token),
            replacement_token_hash=RefreshTokenService.digest(replacement),
            replacement_expires_at=_naive_utc(replacement_expires_at),
            rotated_at=_naive_utc(now),
        )
        if user_id is None:
            raise AuthenticationError("invalid refresh token")
        access = self._access_tokens.issue(user_id, now=now)
        return TokenPair(
            access_token=access.value,
            refresh_token=replacement,
            access_expires_at=access.expires_at,
            refresh_expires_at=replacement_expires_at,
        )

    async def logout(self, refresh_token: str) -> None:
        _validate_refresh_token_shape(refresh_token)
        revoked = await self._repository.revoke_refresh_token(
            token_hash=RefreshTokenService.digest(refresh_token),
            revoked_at=_naive_utc(datetime.now(UTC)),
        )
        if not revoked:
            raise AuthenticationError("invalid refresh token")

    def _build_pair(self, user_id: UUID, now: datetime) -> TokenPair:
        access = self._access_tokens.issue(user_id, now=now)
        return TokenPair(
            access_token=access.value,
            refresh_token=RefreshTokenService.generate(),
            access_expires_at=access.expires_at,
            refresh_expires_at=now + self._refresh_ttl,
        )


def _normalize_username(value: str) -> str:
    normalized = value.strip().casefold()
    if not normalized:
        raise AuthenticationError("invalid credentials")
    return normalized


def _validate_refresh_token_shape(value: str) -> None:
    if not value.startswith(RefreshTokenService.PREFIX) or not 60 <= len(value) <= 128:
        raise AuthenticationError("invalid refresh token")


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None)
