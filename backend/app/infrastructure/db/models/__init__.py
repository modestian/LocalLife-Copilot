"""Database model registry imported by Alembic."""

from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource
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
from app.infrastructure.db.models.sentiment import ReviewAnalysis
from app.infrastructure.db.models.tasks import AsyncTask, OutboxEvent

__all__ = [
    "AsyncTask",
    "Chunk",
    "Conversation",
    "Department",
    "Document",
    "DocumentVersion",
    "KnowledgeBase",
    "Message",
    "MessageSource",
    "OutboxEvent",
    "Permission",
    "RefreshToken",
    "ResourceGrant",
    "ReviewAnalysis",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
]
