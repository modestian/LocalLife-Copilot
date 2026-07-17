from typing import Any

from fastapi import APIRouter, Request

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import AuthorizationPrincipal
from app.core.api import success_response

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me")
async def get_me(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    return success_response(request, _principal_payload(principal))


def _principal_payload(principal: AuthorizationPrincipal) -> dict[str, Any]:
    grouped_scopes: dict[tuple[str, str], set[str]] = {}
    for grant in principal.resource_grants:
        key = (grant.resource_type.value, str(grant.resource_id))
        grouped_scopes.setdefault(key, set()).add(grant.action)

    return {
        "id": str(principal.user_id),
        "username": principal.username,
        "display_name": principal.display_name,
        "email": principal.email,
        "department_id": (
            str(principal.department_id) if principal.department_id is not None else None
        ),
        "roles": [{"code": role.code, "name": role.name} for role in principal.roles],
        "permissions": [permission.code for permission in principal.permissions],
        "resource_scopes": [
            {
                "resource_type": resource_type,
                "resource_id": resource_id,
                "actions": sorted(actions),
            }
            for (resource_type, resource_id), actions in sorted(grouped_scopes.items())
        ],
    }
