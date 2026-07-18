"""Build OpenSearch scopes from authenticated server-side authorization state."""

from collections.abc import Iterable
from uuid import UUID

from app.application.authorization import (
    AuthorizationPrincipal,
    ResourceScopeDenied,
    ResourceType,
)
from app.infrastructure.search.retrieval import TrustedSearchScope


def scope_from_principal(
    principal: AuthorizationPrincipal,
    *,
    tenant_id: UUID,
    requested_knowledge_base_ids: Iterable[UUID],
    action: str = "READ",
) -> TrustedSearchScope:
    """Intersect client-requested knowledge bases with server-side grants."""
    if not principal.is_platform_admin and principal.department_id != tenant_id:
        raise ResourceScopeDenied("tenant scope denied")

    requested = frozenset(requested_knowledge_base_ids)
    allowed = principal.authorized_resource_ids(ResourceType.KNOWLEDGE_BASE, action)
    effective = requested if allowed is None else requested & allowed
    knowledge_base_ids = frozenset(str(value) for value in effective)
    return TrustedSearchScope(
        tenant_id=str(tenant_id),
        knowledge_base_ids=knowledge_base_ids,
        resource_scopes=frozenset(
            f"KNOWLEDGE_BASE:{knowledge_base_id}" for knowledge_base_id in knowledge_base_ids
        ),
    )
