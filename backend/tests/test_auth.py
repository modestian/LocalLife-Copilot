import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import get_auth_service
from app.application.auth import AuthenticationError, AuthService, AuthUser
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.security import (
    AccessTokenService,
    InvalidAccessTokenError,
    PasswordService,
    RefreshTokenService,
)
from app.main import create_app


@dataclass
class StoredRefreshToken:
    user_id: UUID
    expires_at: datetime
    revoked_at: datetime | None = None
    replaced_by_hash: str | None = None


class InMemoryAuthRepository:
    def __init__(self, users: list[AuthUser]) -> None:
        self.users = {str(user.id): user for user in users}
        self.usernames = {"operator01": users[0]} if users else {}
        self.refresh_tokens: dict[str, StoredRefreshToken] = {}
        self.last_stored_hash: str | None = None
        self._rotation_lock = asyncio.Lock()

    async def find_user(self, normalized_username: str) -> AuthUser | None:
        return self.usernames.get(normalized_username)

    async def create_refresh_token(
        self,
        *,
        user_id: UUID,
        token_hash: str,
        expires_at: datetime,
        authenticated_at: datetime,
    ) -> bool:
        del authenticated_at
        user = self.users.get(str(user_id))
        if user is None or not user.can_authenticate:
            return False
        self.refresh_tokens[token_hash] = StoredRefreshToken(user_id, expires_at)
        self.last_stored_hash = token_hash
        return True

    async def rotate_refresh_token(
        self,
        *,
        current_token_hash: str,
        replacement_token_hash: str,
        replacement_expires_at: datetime,
        rotated_at: datetime,
    ) -> UUID | None:
        # Models the SELECT ... FOR UPDATE critical section in SQLAlchemyAuthRepository.
        async with self._rotation_lock:
            current = self.refresh_tokens.get(current_token_hash)
            if (
                current is None
                or current.revoked_at is not None
                or current.expires_at <= rotated_at
                or not self.users[str(current.user_id)].can_authenticate
            ):
                return None
            current.revoked_at = rotated_at
            current.replaced_by_hash = replacement_token_hash
            self.refresh_tokens[replacement_token_hash] = StoredRefreshToken(
                current.user_id, replacement_expires_at
            )
            self.last_stored_hash = replacement_token_hash
            return current.user_id

    async def revoke_refresh_token(self, *, token_hash: str, revoked_at: datetime) -> bool:
        current = self.refresh_tokens.get(token_hash)
        if current is None or current.revoked_at is not None or current.expires_at <= revoked_at:
            return False
        current.revoked_at = revoked_at
        return True


@pytest.fixture(scope="module")
def password_service() -> PasswordService:
    return PasswordService()


@pytest.fixture
def auth_components(
    password_service: PasswordService,
) -> tuple[AuthService, InMemoryAuthRepository, AccessTokenService]:
    user = AuthUser(
        id=uuid7(),
        password_hash=password_service.hash("correct horse battery staple"),
        status="ACTIVE",
    )
    repository = InMemoryAuthRepository([user])
    access_tokens = AccessTokenService(
        secret_key="test-secret-key-with-at-least-32-bytes",
        issuer="test-issuer",
        audience="test-audience",
        ttl=timedelta(minutes=30),
    )
    service = AuthService(
        repository,
        password_service,
        access_tokens,
        refresh_ttl=timedelta(days=7),
    )
    return service, repository, access_tokens


def test_passwords_use_argon2id_with_random_salts(password_service: PasswordService) -> None:
    first = password_service.hash("same-password")
    second = password_service.hash("same-password")

    assert first.startswith("$argon2id$")
    assert second.startswith("$argon2id$")
    assert first != second
    assert password_service.verify(first, "same-password")
    assert not password_service.verify(first, "wrong-password")
    assert not password_service.verify("not-a-valid-hash", "same-password")


def test_access_jwt_has_strict_identity_and_lifetime_claims() -> None:
    service = AccessTokenService(
        secret_key="test-secret-key-with-at-least-32-bytes",
        issuer="expected-issuer",
        audience="expected-audience",
        ttl=timedelta(minutes=30),
    )
    user_id = uuid7()
    encoded = service.issue(user_id)
    claims = service.decode(encoded.value)

    assert claims.user_id == user_id
    assert claims.expires_at - claims.issued_at == timedelta(minutes=30)
    assert claims.token_id.version == 7

    wrong_audience = AccessTokenService(
        secret_key="test-secret-key-with-at-least-32-bytes",
        issuer="expected-issuer",
        audience="another-audience",
        ttl=timedelta(minutes=30),
    )
    with pytest.raises(InvalidAccessTokenError):
        wrong_audience.decode(encoded.value)


def test_access_jwt_rejects_expired_and_wrong_type_tokens() -> None:
    secret = "test-secret-key-with-at-least-32-bytes"
    service = AccessTokenService(
        secret_key=secret,
        issuer="issuer",
        audience="audience",
        ttl=timedelta(minutes=1),
    )
    expired = service.issue(uuid7(), now=datetime.now(UTC) - timedelta(minutes=2))
    with pytest.raises(InvalidAccessTokenError):
        service.decode(expired.value)

    now = datetime.now(UTC)
    refresh_jwt = jwt.encode(
        {
            "iss": "issuer",
            "aud": "audience",
            "sub": str(uuid7()),
            "jti": str(uuid7()),
            "type": "refresh",
            "iat": now,
            "nbf": now,
            "exp": now + timedelta(minutes=1),
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(InvalidAccessTokenError):
        service.decode(refresh_jwt)


def test_refresh_tokens_are_opaque_high_entropy_values() -> None:
    first = RefreshTokenService.generate()
    second = RefreshTokenService.generate()

    assert first.startswith("rt_")
    assert len(first) >= 60
    assert first != second
    assert len(RefreshTokenService.digest(first)) == 64
    assert RefreshTokenService.digest(first) != RefreshTokenService.digest(second)


@pytest.mark.asyncio
async def test_login_stores_only_refresh_digest_and_issues_valid_access_token(
    auth_components: tuple[AuthService, InMemoryAuthRepository, AccessTokenService],
) -> None:
    service, repository, access_tokens = auth_components
    pair = await service.login("  Operator01  ", "correct horse battery staple")

    assert repository.last_stored_hash == RefreshTokenService.digest(pair.refresh_token)
    assert pair.refresh_token not in repository.refresh_tokens
    stored_user = next(iter(repository.users.values()))
    assert access_tokens.decode(pair.access_token).user_id == stored_user.id


@pytest.mark.asyncio
async def test_invalid_password_and_disabled_user_share_same_failure(
    auth_components: tuple[AuthService, InMemoryAuthRepository, AccessTokenService],
) -> None:
    service, repository, _ = auth_components
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await service.login("operator01", "incorrect")

    user = repository.usernames["operator01"]
    repository.usernames["operator01"] = AuthUser(user.id, user.password_hash, "DISABLED")
    with pytest.raises(AuthenticationError, match="invalid credentials"):
        await service.login("operator01", "correct horse battery staple")


@pytest.mark.asyncio
async def test_refresh_rotation_invalidates_old_token_and_logout_revokes_new_token(
    auth_components: tuple[AuthService, InMemoryAuthRepository, AccessTokenService],
) -> None:
    service, _, _ = auth_components
    original = await service.login("operator01", "correct horse battery staple")
    rotated = await service.refresh(original.refresh_token)

    assert rotated.refresh_token != original.refresh_token
    with pytest.raises(AuthenticationError, match="invalid refresh token"):
        await service.refresh(original.refresh_token)

    await service.logout(rotated.refresh_token)
    with pytest.raises(AuthenticationError, match="invalid refresh token"):
        await service.refresh(rotated.refresh_token)


@pytest.mark.asyncio
async def test_concurrent_refresh_allows_exactly_one_rotation(
    auth_components: tuple[AuthService, InMemoryAuthRepository, AccessTokenService],
) -> None:
    service, _, _ = auth_components
    original = await service.login("operator01", "correct horse battery staple")
    results = await asyncio.gather(
        service.refresh(original.refresh_token),
        service.refresh(original.refresh_token),
        return_exceptions=True,
    )

    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert sum(isinstance(result, AuthenticationError) for result in results) == 1


def test_auth_api_login_refresh_replay_and_logout(
    auth_components: tuple[AuthService, InMemoryAuthRepository, AccessTokenService],
) -> None:
    service, _, _ = auth_components
    app = create_app(readiness_checks={}, settings=Settings())
    app.dependency_overrides[get_auth_service] = lambda: service

    with TestClient(app) as client:
        bad_login = client.post(
            "/api/v1/auth/login",
            json={"username": "operator01", "password": "incorrect"},
        )
        login = client.post(
            "/api/v1/auth/login",
            json={
                "username": "operator01",
                "password": "correct horse battery staple",
            },
        )
        first_refresh = login.json()["data"]["refresh_token"]
        refresh = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
        replay = client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
        replacement = refresh.json()["data"]["refresh_token"]
        logout = client.post("/api/v1/auth/logout", json={"refresh_token": replacement})
        after_logout = client.post("/api/v1/auth/refresh", json={"refresh_token": replacement})

    assert bad_login.status_code == 401
    assert bad_login.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert login.status_code == 200
    assert login.json()["data"]["token_type"] == "bearer"
    assert login.json()["data"]["expires_in"] == 1800
    assert refresh.status_code == 200
    assert replay.status_code == 401
    assert replay.json()["code"] == "AUTH_INVALID_REFRESH_TOKEN"
    assert logout.status_code == 200
    assert after_logout.status_code == 401
