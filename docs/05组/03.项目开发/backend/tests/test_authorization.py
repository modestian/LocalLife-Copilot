from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import Column, MetaData, Table, Uuid, select

from app.api.dependencies.authorization import (
    get_authorization_service,
    require_permission,
    require_resource_access,
)
from app.application.authorization import (
    AuthenticationRequired,
    AuthorizationDenied,
    AuthorizationPrincipal,
    AuthorizationService,
    PermissionRule,
    ResourceGrantRule,
    ResourceType,
    RoleInfo,
    filter_authorized_resources,
)
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.security import AccessTokenService
from app.infrastructure.db.repositories.scoped import apply_resource_scope
from app.main import create_app


class InMemoryAuthorizationRepository:
    def __init__(self, principals: list[AuthorizationPrincipal]) -> None:
        self.principals = {principal.user_id: principal for principal in principals}

    async def load_principal(self, user_id: UUID) -> AuthorizationPrincipal | None:
        return self.principals.get(user_id)


@dataclass(frozen=True)
class ProtectedResource:
    id: UUID
    name: str


@pytest.fixture
def scoped_principal() -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="kb_operator",
        display_name="Knowledge base operator",
        email="operator@example.com",
        department_id=uuid7(),
        roles=(RoleInfo("KB_ADMIN", "知识库管理员"),),
        permissions=(
            PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),
            PermissionRule("merchant.read", "MERCHANT", "READ"),
            PermissionRule("region.read", "REGION", "READ"),
        ),
        resource_grants=(
            ResourceGrantRule(ResourceType.KNOWLEDGE_BASE, uuid7(), "READ"),
            ResourceGrantRule(ResourceType.MERCHANT, uuid7(), "READ"),
            ResourceGrantRule(ResourceType.REGION, uuid7(), "READ"),
        ),
    )


def test_rbac_and_resource_scope_are_both_required(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    allowed_kb = scoped_principal.resource_grants[0].resource_id
    scoped_principal.require_resource_access(ResourceType.KNOWLEDGE_BASE, allowed_kb, "READ")

    with pytest.raises(AuthorizationDenied, match="resource scope denied"):
        scoped_principal.require_resource_access(ResourceType.KNOWLEDGE_BASE, uuid7(), "READ")
    with pytest.raises(AuthorizationDenied, match="role permission denied"):
        scoped_principal.require_resource_access(ResourceType.KNOWLEDGE_BASE, allowed_kb, "DELETE")


def test_interface_results_are_filtered_to_authorized_ids(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    allowed_id = scoped_principal.resource_grants[0].resource_id
    resources = [
        ProtectedResource(allowed_id, "visible"),
        ProtectedResource(uuid7(), "hidden"),
    ]

    visible = filter_authorized_resources(
        scoped_principal,
        resources,
        resource_type=ResourceType.KNOWLEDGE_BASE,
        action="READ",
        id_getter=lambda resource: resource.id,
    )

    assert [resource.name for resource in visible] == ["visible"]


def test_platform_admin_bypasses_resource_ids_but_not_authentication() -> None:
    principal = AuthorizationPrincipal(
        user_id=uuid7(),
        username="admin",
        display_name="Admin",
        email=None,
        department_id=None,
        roles=(RoleInfo("PLATFORM_ADMIN", "平台管理员"),),
        permissions=(),
        resource_grants=(),
    )

    principal.require_resource_access(ResourceType.MERCHANT, uuid7(), "DELETE")
    assert principal.authorized_resource_ids(ResourceType.REGION, "READ") is None


def test_repository_query_always_applies_resource_scope(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    table = Table("protected_items", MetaData(), Column("resource_id", Uuid))
    base_statement = select(table)

    for resource_type in ResourceType:
        scoped_statement = apply_resource_scope(
            base_statement,
            principal=scoped_principal,
            resource_type=resource_type,
            action="READ",
            resource_id_column=table.c.resource_id,
        )
        assert len(scoped_statement._where_criteria) == 1
        assert " IN " in str(scoped_statement)

    no_grants = AuthorizationPrincipal(
        user_id=uuid7(),
        username="no_scope",
        display_name="No scope",
        email=None,
        department_id=None,
        roles=(),
        permissions=(PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),),
        resource_grants=(),
    )
    empty_statement = apply_resource_scope(
        base_statement,
        principal=no_grants,
        resource_type=ResourceType.KNOWLEDGE_BASE,
        action="READ",
        resource_id_column=table.c.resource_id,
    )
    assert "false" in str(empty_statement).lower()


@pytest.mark.asyncio
async def test_authorization_service_rejects_invalid_or_unknown_access_token(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    access_tokens = _access_tokens()
    service = AuthorizationService(
        InMemoryAuthorizationRepository([scoped_principal]), access_tokens
    )

    with pytest.raises(AuthenticationRequired):
        await service.authenticate("invalid")

    unknown_token = access_tokens.issue(uuid7()).value
    with pytest.raises(AuthenticationRequired):
        await service.authenticate(unknown_token)


@pytest.mark.asyncio
async def test_authorization_service_rejects_access_token_issued_before_logout() -> None:
    access_tokens = _access_tokens()
    issued_at = datetime.now(UTC)
    principal = AuthorizationPrincipal(
        user_id=uuid7(),
        username="logged-out-user",
        display_name="Logged out user",
        email=None,
        department_id=uuid7(),
        roles=(RoleInfo("USER", "User"),),
        permissions=(),
        resource_grants=(),
        access_tokens_valid_after=issued_at + timedelta(microseconds=1),
    )
    service = AuthorizationService(InMemoryAuthorizationRepository([principal]), access_tokens)

    with pytest.raises(AuthenticationRequired, match="revoked access token"):
        await service.authenticate(access_tokens.issue(principal.user_id, now=issued_at).value)


def test_users_me_and_authorization_dependencies(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    access_tokens = _access_tokens()
    allowed_kb = scoped_principal.resource_grants[0].resource_id
    no_permission = AuthorizationPrincipal(
        user_id=uuid7(),
        username="ordinary_user",
        display_name="Ordinary user",
        email=None,
        department_id=None,
        roles=(RoleInfo("USER", "普通用户"),),
        permissions=(),
        resource_grants=(),
    )
    no_scope = AuthorizationPrincipal(
        user_id=uuid7(),
        username="kb_reader_without_scope",
        display_name="KB reader without scope",
        email=None,
        department_id=None,
        roles=(RoleInfo("KB_READER", "KB reader"),),
        permissions=(PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),),
        resource_grants=(),
    )
    service = AuthorizationService(
        InMemoryAuthorizationRepository([scoped_principal, no_permission, no_scope]),
        access_tokens,
    )
    app = create_app(readiness_checks={}, settings=Settings())
    app.dependency_overrides[get_authorization_service] = lambda: service

    permission_dependency = require_permission("KNOWLEDGE_BASE", "READ")
    resource_dependency = require_resource_access(
        ResourceType.KNOWLEDGE_BASE,
        "READ",
        path_parameter="knowledge_base_id",
    )

    @app.get("/test/permission")
    async def permission_probe(
        principal: Annotated[AuthorizationPrincipal, Depends(permission_dependency)],
    ) -> dict[str, str]:
        return {"user_id": str(principal.user_id)}

    @app.get("/test/knowledge-bases/{knowledge_base_id}")
    async def resource_probe(
        knowledge_base_id: UUID,
        principal: Annotated[AuthorizationPrincipal, Depends(resource_dependency)],
    ) -> dict[str, str]:
        return {"id": str(knowledge_base_id), "user_id": str(principal.user_id)}

    scoped_token = access_tokens.issue(scoped_principal.user_id).value
    ordinary_token = access_tokens.issue(no_permission.user_id).value
    no_scope_token = access_tokens.issue(no_scope.user_id).value
    unknown_token = access_tokens.issue(uuid7()).value

    with TestClient(app) as client:
        missing = client.get("/api/v1/users/me")
        invalid = client.get("/api/v1/users/me", headers={"Authorization": "Bearer invalid"})
        unknown = client.get(
            "/api/v1/users/me", headers={"Authorization": f"Bearer {unknown_token}"}
        )
        me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {scoped_token}"})
        forbidden = client.get(
            "/test/permission", headers={"Authorization": f"Bearer {ordinary_token}"}
        )
        resource_forbidden = client.get(
            f"/test/knowledge-bases/{allowed_kb}",
            headers={"Authorization": f"Bearer {ordinary_token}"},
        )
        scoped_out = client.get(
            f"/test/knowledge-bases/{allowed_kb}",
            headers={"Authorization": f"Bearer {no_scope_token}"},
        )
        allowed = client.get(
            f"/test/knowledge-bases/{allowed_kb}",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )
        hidden = client.get(
            f"/test/knowledge-bases/{uuid7()}",
            headers={"Authorization": f"Bearer {scoped_token}"},
        )

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert invalid.status_code == 401
    assert unknown.status_code == 401
    assert me.status_code == 200
    assert me.json()["data"]["username"] == scoped_principal.username
    assert me.json()["data"]["roles"] == [{"code": "KB_ADMIN", "name": "知识库管理员"}]
    assert {scope["resource_type"] for scope in me.json()["data"]["resource_scopes"]} == {
        "KNOWLEDGE_BASE",
        "MERCHANT",
        "REGION",
    }
    assert forbidden.status_code == 403
    assert resource_forbidden.status_code == 403
    assert resource_forbidden.json()["code"] == "FORBIDDEN"
    assert scoped_out.status_code == 404
    assert scoped_out.json()["code"] == "NOT_FOUND"
    assert allowed.status_code == 200
    assert hidden.status_code == 404


def test_real_merchant_endpoints_enforce_rbac_and_resource_scope() -> None:
    from app.api.analytics import get_analytics_service

    class StubAnalyticsService:
        async def get_sentiment_trend(self, *args, **kwargs) -> list[dict]:
            return []

        async def compare_merchants(self, merchant_ids, **kwargs) -> dict:
            return {
                "merchants": merchant_ids,
                "summary": [],
                "aspect_comparison": [],
                "negative_reason_comparison": [],
            }

    access_tokens = _access_tokens()
    allowed_merchant = uuid7()
    hidden_merchant = uuid7()
    allowed = AuthorizationPrincipal(
        user_id=uuid7(),
        username="merchant-reader",
        display_name="Merchant reader",
        email=None,
        department_id=None,
        roles=(RoleInfo("MERCHANT_READER", "Merchant reader"),),
        permissions=(PermissionRule("merchant.read", "MERCHANT", "READ"),),
        resource_grants=(ResourceGrantRule(ResourceType.MERCHANT, allowed_merchant, "READ"),),
    )
    no_permission = AuthorizationPrincipal(
        user_id=uuid7(),
        username="ordinary-user",
        display_name="Ordinary user",
        email=None,
        department_id=None,
        roles=(RoleInfo("USER", "User"),),
        permissions=(),
        resource_grants=(),
    )
    service = AuthorizationService(
        InMemoryAuthorizationRepository([allowed, no_permission]),
        access_tokens,
    )
    app = create_app(readiness_checks={}, settings=Settings())
    app.dependency_overrides[get_authorization_service] = lambda: service
    app.dependency_overrides[get_analytics_service] = lambda: StubAnalyticsService()

    allowed_headers = {"Authorization": f"Bearer {access_tokens.issue(allowed.user_id).value}"}
    denied_headers = {"Authorization": f"Bearer {access_tokens.issue(no_permission.user_id).value}"}

    with TestClient(app) as client:
        unauthenticated = client.get(
            f"/api/v1/merchants/{allowed_merchant}/analytics/sentiment-trend"
        )
        forbidden = client.get(
            f"/api/v1/merchants/{allowed_merchant}/analytics/sentiment-trend",
            headers=denied_headers,
        )
        hidden = client.get(
            f"/api/v1/merchants/{hidden_merchant}/analytics/sentiment-trend",
            headers=allowed_headers,
        )
        visible = client.get(
            f"/api/v1/merchants/{allowed_merchant}/analytics/sentiment-trend",
            headers=allowed_headers,
        )
        mixed_comparison = client.get(
            "/api/v1/analytics/compare",
            params=[
                ("merchant_ids", str(allowed_merchant)),
                ("merchant_ids", str(hidden_merchant)),
            ],
            headers=allowed_headers,
        )

    assert unauthenticated.status_code == 401
    assert forbidden.status_code == 403
    assert hidden.status_code == 404
    assert visible.status_code == 200
    assert mixed_comparison.status_code == 404


def test_non_admin_cannot_create_knowledge_base_for_another_tenant_or_owner() -> None:
    access_tokens = _access_tokens()
    principal = AuthorizationPrincipal(
        user_id=uuid7(),
        username="kb-creator",
        display_name="Knowledge base creator",
        email=None,
        department_id=uuid7(),
        roles=(RoleInfo("KB_ADMIN", "Knowledge base admin"),),
        permissions=(PermissionRule("kb.create", "KNOWLEDGE_BASE", "CREATE"),),
        resource_grants=(),
    )
    service = AuthorizationService(InMemoryAuthorizationRepository([principal]), access_tokens)
    app = create_app(readiness_checks={}, settings=Settings())
    app.dependency_overrides[get_authorization_service] = lambda: service
    headers = {"Authorization": f"Bearer {access_tokens.issue(principal.user_id).value}"}
    base_payload = {
        "name": "Protected knowledge base",
        "embedding_model_id": str(uuid7()),
    }

    with TestClient(app) as client:
        other_tenant = client.post(
            "/api/v1/knowledge-bases",
            headers=headers,
            json={**base_payload, "department_id": str(uuid7())},
        )
        other_owner = client.post(
            "/api/v1/knowledge-bases",
            headers=headers,
            json={**base_payload, "owner_id": str(uuid7())},
        )

    assert other_tenant.status_code == 403
    assert other_tenant.json()["code"] == "FORBIDDEN"
    assert other_owner.status_code == 403
    assert other_owner.json()["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_scoped_sentiment_repository_rejects_horizontal_access_before_query(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    from unittest.mock import MagicMock

    from app.infrastructure.db.repositories.sentiment import SQLAlchemySentimentRepository

    repository = SQLAlchemySentimentRepository(  # type: ignore[arg-type]
        MagicMock(),
        principal=scoped_principal,
    )

    with pytest.raises(AuthorizationDenied, match="resource scope denied"):
        await repository.get_sentiment_trend(str(uuid7()))


@pytest.mark.asyncio
async def test_scoped_sentiment_repository_hides_review_owned_by_another_merchant(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.infrastructure.db.repositories.sentiment import SQLAlchemySentimentRepository

    session = AsyncMock()
    session.scalar.return_value = None
    context = AsyncMock()
    context.__aenter__.return_value = session
    session_factory = MagicMock(return_value=context)
    repository = SQLAlchemySentimentRepository(
        session_factory,
        principal=scoped_principal,
    )

    assert await repository.find_review_by_id(uuid7()) is None
    statement = session.scalar.await_args.args[0]
    sql = str(statement)
    assert "review_analyses.merchant_id IN" in sql
    compiled_values = statement.compile().params.values()
    assert any(
        str(scoped_principal.resource_grants[1].resource_id) in value
        for value in compiled_values
        if isinstance(value, list)
    )


@pytest.mark.asyncio
async def test_scoped_knowledge_repository_filters_before_database_pagination(
    scoped_principal: AuthorizationPrincipal,
) -> None:
    from unittest.mock import AsyncMock, MagicMock

    from app.infrastructure.db.repositories.knowledge import SQLAlchemyKnowledgeRepository

    scalar_result = MagicMock()
    scalar_result.all.return_value = []
    session = AsyncMock()
    session.scalars.return_value = scalar_result
    context = AsyncMock()
    context.__aenter__.return_value = session
    session_factory = MagicMock(return_value=context)
    repository = SQLAlchemyKnowledgeRepository(
        session_factory,
        principal=scoped_principal,
    )

    assert await repository.list_knowledge_bases(scoped_principal.department_id) == []
    statement = session.scalars.await_args.args[0]
    sql = str(statement)
    assert "knowledge_bases.id IN" in sql
    assert sql.index("knowledge_bases.id IN") < sql.index("LIMIT")


def _access_tokens() -> AccessTokenService:
    return AccessTokenService(
        secret_key="authorization-test-secret-at-least-32-bytes",
        issuer="authorization-test",
        audience="authorization-api",
        ttl=timedelta(minutes=30),
    )
