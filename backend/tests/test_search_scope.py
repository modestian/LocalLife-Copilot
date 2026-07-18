from uuid import UUID

import pytest

from app.application.authorization import (
    AuthorizationPrincipal,
    PermissionRule,
    ResourceGrantRule,
    ResourceScopeDenied,
    ResourceType,
    RoleInfo,
)
from app.infrastructure.search.scope import scope_from_principal

TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b121")
OTHER_TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b122")
ALLOWED_KB_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b123")
DENIED_KB_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b124")


def principal(*, admin: bool = False) -> AuthorizationPrincipal:
    return AuthorizationPrincipal(
        user_id=UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125"),
        username="search-user",
        display_name="Search User",
        email=None,
        department_id=TENANT_ID,
        roles=(RoleInfo("PLATFORM_ADMIN", "Admin"),) if admin else (),
        permissions=(PermissionRule("kb.read", "KNOWLEDGE_BASE", "READ"),),
        resource_grants=(ResourceGrantRule(ResourceType.KNOWLEDGE_BASE, ALLOWED_KB_ID, "READ"),),
    )


def test_scope_intersects_requested_knowledge_bases_with_server_grants() -> None:
    scope = scope_from_principal(
        principal(),
        tenant_id=TENANT_ID,
        requested_knowledge_base_ids=[ALLOWED_KB_ID, DENIED_KB_ID],
    )

    assert scope.tenant_id == str(TENANT_ID)
    assert scope.knowledge_base_ids == frozenset({str(ALLOWED_KB_ID)})
    assert scope.resource_scopes == frozenset({f"KNOWLEDGE_BASE:{ALLOWED_KB_ID}"})


def test_scope_rejects_cross_tenant_search_before_opensearch() -> None:
    with pytest.raises(ResourceScopeDenied, match="tenant scope denied"):
        scope_from_principal(
            principal(),
            tenant_id=OTHER_TENANT_ID,
            requested_knowledge_base_ids=[ALLOWED_KB_ID],
        )


def test_platform_admin_may_select_requested_knowledge_bases_in_explicit_tenant() -> None:
    scope = scope_from_principal(
        principal(admin=True),
        tenant_id=OTHER_TENANT_ID,
        requested_knowledge_base_ids=[DENIED_KB_ID],
    )

    assert scope.tenant_id == str(OTHER_TENANT_ID)
    assert scope.knowledge_base_ids == frozenset({str(DENIED_KB_ID)})
