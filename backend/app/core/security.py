from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type

from app.core.ids import uuid7


class InvalidAccessTokenError(ValueError):
    """Raised when an access token is invalid, expired, or has unexpected claims."""


@dataclass(frozen=True, slots=True)
class EncodedAccessToken:
    value: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    user_id: UUID
    token_id: UUID
    issued_at: datetime
    expires_at: datetime


class PasswordService:
    """Hash and verify passwords with the Argon2id profile used by the application."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )
        # Used when a username is absent so the failure path still performs Argon2 work.
        self._dummy_hash = self._hasher.hash("local-life-copilot-dummy-password")

    def hash(self, password: str) -> str:
        if not password:
            raise ValueError("password must not be empty")
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False

    def verify_dummy(self, password: str) -> None:
        self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True


class AccessTokenService:
    ALGORITHM = "HS256"

    def __init__(
        self,
        *,
        secret_key: str,
        issuer: str,
        audience: str,
        ttl: timedelta,
    ) -> None:
        if len(secret_key.encode("utf-8")) < 32:
            raise ValueError("secret_key must contain at least 32 bytes")
        if ttl <= timedelta(0):
            raise ValueError("access token ttl must be positive")
        self._secret_key = secret_key
        self._issuer = issuer
        self._audience = audience
        self._ttl = ttl

    def issue(self, user_id: UUID, *, now: datetime | None = None) -> EncodedAccessToken:
        issued_at = _aware_utc(now)
        expires_at = issued_at + self._ttl
        payload: dict[str, Any] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": str(user_id),
            "jti": str(uuid7()),
            "type": "access",
            "iat": issued_at,
            "nbf": issued_at,
            "exp": expires_at,
        }
        return EncodedAccessToken(
            value=jwt.encode(payload, self._secret_key, algorithm=self.ALGORITHM),
            expires_at=expires_at,
        )

    def decode(self, token: str) -> AccessTokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret_key,
                algorithms=[self.ALGORITHM],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["iss", "aud", "sub", "jti", "type", "iat", "nbf", "exp"]},
            )
            if payload["type"] != "access":
                raise InvalidAccessTokenError("unexpected token type")
            return AccessTokenClaims(
                user_id=UUID(payload["sub"]),
                token_id=UUID(payload["jti"]),
                issued_at=datetime.fromtimestamp(payload["iat"], UTC),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, InvalidAccessTokenError):
                raise
            raise InvalidAccessTokenError("invalid access token") from exc


class RefreshTokenService:
    PREFIX = "rt_"

    @classmethod
    def generate(cls) -> str:
        # 48 random bytes provide 384 bits of entropy before URL-safe encoding.
        return f"{cls.PREFIX}{token_urlsafe(48)}"

    @staticmethod
    def digest(token: str) -> str:
        return sha256(token.encode("utf-8")).hexdigest()


def _aware_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
