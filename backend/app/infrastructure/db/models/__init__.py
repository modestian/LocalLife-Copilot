"""Database model registry imported by Alembic."""

from app.infrastructure.db.models.conversations import Conversation, Message, MessageSource
from app.infrastructure.db.models.feedback import (
    Dataset,
    DatasetItem,
    Feedback,
    FeedbackAudit,
)
from app.infrastructure.db.models.governance import (
    AuditLog,
    ModelDefinition,
    ModelDeployment,
    ModelDeploymentRoute,
    ModelVersion,
    PromptDefinition,
    PromptVersion,
    SensitiveWordRule,
)
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
    "AuditLog",
    "AsyncTask",
    "Chunk",
    "Conversation",
    "Dataset",
    "DatasetItem",
    "Department",
    "Document",
    "DocumentVersion",
    "Feedback",
    "FeedbackAudit",
    "KnowledgeBase",
    "Message",
    "MessageSource",
    "ModelDefinition",
    "ModelDeployment",
    "ModelDeploymentRoute",
    "ModelVersion",
    "OutboxEvent",
    "Permission",
    "PromptDefinition",
    "PromptVersion",
    "RefreshToken",
    "ResourceGrant",
    "ReviewAnalysis",
    "Role",
    "RolePermission",
    "SensitiveWordRule",
    "User",
    "UserRole",
]
