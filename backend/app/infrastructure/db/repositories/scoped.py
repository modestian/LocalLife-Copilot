from typing import Any

from sqlalchemy import false
from sqlalchemy.sql import ColumnElement, Select

from app.application.authorization import AuthorizationPrincipal, ResourceType


def apply_resource_scope[RowT](
    statement: Select[tuple[RowT]],
    *,
    principal: AuthorizationPrincipal,
    resource_type: ResourceType | str,
    action: str,
    resource_id_column: ColumnElement[Any],
) -> Select[tuple[RowT]]:
    """Apply the mandatory resource predicate before a repository executes a query."""
    allowed_ids = principal.authorized_resource_ids(resource_type, action)
    if allowed_ids is None:
        return statement
    if not allowed_ids:
        return statement.where(false())
    return statement.where(resource_id_column.in_(allowed_ids))
