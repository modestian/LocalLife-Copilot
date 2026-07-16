"""Database model registry imported by Alembic."""

from app.infrastructure.db.models.identity import (
    Department,
    Permission,
    RefreshToken,
    ResourceGrant,
    Role,
    RolePermission,
    User,
    UserRole,
)

__all__ = [
    "Department",
    "Permission",
    "RefreshToken",
    "ResourceGrant",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
]
