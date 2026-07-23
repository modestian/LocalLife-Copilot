"""Database-backed resolver for the shared public chat corpus."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.contracts import RetrievalScope
from app.application.chat_knowledge import PublicKnowledgeBase, build_shared_chat_scope
from app.infrastructure.db.models.identity import ResourceGrant, Role
from app.infrastructure.db.models.knowledge import KnowledgeBase


class SQLAlchemySharedChatKnowledgeScopeResolver:
    """Resolve active knowledge bases granted READ access to the USER role."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def resolve(self, requested_ids: Sequence[UUID]) -> RetrievalScope:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(KnowledgeBase.id, KnowledgeBase.tenant_id)
                    .join(
                        ResourceGrant,
                        and_(
                            ResourceGrant.resource_type == "KNOWLEDGE_BASE",
                            ResourceGrant.resource_id == KnowledgeBase.id,
                            ResourceGrant.subject_type == "ROLE",
                        ),
                    )
                    .join(Role, Role.id == ResourceGrant.subject_id)
                    .where(
                        Role.code == "USER",
                        Role.status == "ACTIVE",
                        or_(ResourceGrant.action == "READ", ResourceGrant.action == "*"),
                        KnowledgeBase.status == "ACTIVE",
                        KnowledgeBase.deleted_at.is_(None),
                    )
                    .distinct()
                    .order_by(KnowledgeBase.id)
                )
            ).all()
        return build_shared_chat_scope(
            (PublicKnowledgeBase(id=row.id, tenant_id=row.tenant_id) for row in rows),
            requested_ids,
        )
