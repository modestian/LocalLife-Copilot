from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.authorization import get_current_principal
from app.api.identity_management import router
from app.application.authorization import AuthorizationPrincipal, RoleInfo
from app.core.api import install_api_contract
from app.core.config import Settings
from app.core.ids import uuid7
from app.main import create_app


def _principal(*, admin: bool = True) -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="identity-admin",
        display_name="Identity admin",
        email=None,
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "平台管理员"),) if admin else (),
        permissions=(),
        resource_grants=(),
    )


class IdentityRepositoryStub:
    def __init__(self) -> None:
        self.created = None
        self.password_reset = None
        self.deleted_user_id = None

    async def list_users(self, **values):
        del values
        return (
            [
                {
                    "id": str(uuid7()),
                    "username": "operator01",
                    "display_name": "Operator",
                    "email": None,
                    "department_id": None,
                    "status": "ACTIVE",
                    "roles": [],
                    "resource_scopes": [],
                    "last_login_at": None,
                    "created_at": "2026-07-23T00:00:00",
                    "updated_at": "2026-07-23T00:00:00",
                }
            ],
            1,
        )

    async def create_user(self, value, **context):
        self.created = (value, context)
        return {
            "id": str(uuid7()),
            "username": value.username,
            "display_name": value.display_name,
            "email": value.email,
            "department_id": None,
            "status": "ACTIVE",
            "roles": [],
            "resource_scopes": [],
            "last_login_at": None,
            "created_at": "2026-07-23T00:00:00",
            "updated_at": "2026-07-23T00:00:00",
        }

    async def delete_user(self, user_id, **context):
        del context
        self.deleted_user_id = user_id

    async def reset_password(self, user_id, password_hash, **context):
        self.password_reset = (user_id, password_hash, context)


def _client(
    repository: IdentityRepositoryStub, *, admin: bool = True
) -> tuple[TestClient, AuthorizationPrincipal]:
    app = FastAPI()
    settings = Settings()
    install_api_contract(app, settings)
    app.include_router(router, prefix=settings.api_v1_prefix)
    principal = _principal(admin=admin)
    app.state.identity_management_repository = repository
    app.dependency_overrides[get_current_principal] = lambda: principal
    return TestClient(app), principal


def test_production_application_exposes_identity_management_routes() -> None:
    app = create_app(readiness_checks={})
    schema = app.openapi()
    route_methods = {
        (path, method.upper())
        for path, methods in schema.get("paths", {}).items()
        for method in methods
    }
    assert {
        ("/api/v1/users", "GET"),
        ("/api/v1/users", "POST"),
        ("/api/v1/users/{user_id}", "PATCH"),
        ("/api/v1/users/{user_id}", "DELETE"),
        ("/api/v1/users/{user_id}/roles", "PUT"),
        ("/api/v1/users/{user_id}/reset-password", "POST"),
        ("/api/v1/roles", "GET"),
        ("/api/v1/roles", "POST"),
        ("/api/v1/roles/{role_id}/permissions", "PUT"),
        ("/api/v1/permissions", "GET"),
    } <= route_methods


def test_only_platform_admin_can_list_users() -> None:
    repository = IdentityRepositoryStub()
    client, _ = _client(repository, admin=False)
    with client:
        response = client.get("/api/v1/users")
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_admin_can_list_and_create_user_with_hashed_password() -> None:
    repository = IdentityRepositoryStub()
    role_id = uuid7()
    client, _ = _client(repository)
    with client:
        listed = client.get("/api/v1/users")
        created = client.post(
            "/api/v1/users",
            json={
                "username": "new.operator",
                "display_name": "New operator",
                "password": "correct-horse-battery",
                "role_ids": [str(role_id)],
                "resource_grants": [],
            },
        )

    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1
    assert created.status_code == 201
    value, _ = repository.created
    assert value.role_ids == (role_id,)
    assert value.password_hash.startswith("$argon2id$")
    assert "correct-horse-battery" not in value.password_hash


def test_admin_cannot_delete_current_account() -> None:
    repository = IdentityRepositoryStub()
    client, principal = _client(repository)
    with client:
        response = client.delete(f"/api/v1/users/{principal.user_id}")
    assert response.status_code == 409
    assert response.json()["code"] == "SELF_DELETE_FORBIDDEN"
    assert repository.deleted_user_id is None


def test_admin_can_reset_own_password_and_revoke_sessions() -> None:
    repository = IdentityRepositoryStub()
    client, principal = _client(repository)
    with client:
        response = client.post(
            f"/api/v1/users/{principal.user_id}/reset-password",
            json={"password": "new-platform-password"},
        )
    assert response.status_code == 200
    assert response.json()["data"] == {
        "id": str(principal.user_id),
        "sessions_revoked": True,
    }

    user_id, password_hash, context = repository.password_reset
    assert user_id == principal.user_id
    assert password_hash.startswith("$argon2id$")
    assert "new-platform-password" not in password_hash
    assert context["actor_id"] == principal.user_id
