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
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase

__all__ = [
    "Chunk",
    "Department",
    "Document",
    "DocumentVersion",
    "KnowledgeBase",
    "Permission",
    "RefreshToken",
    "ResourceGrant",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
]
