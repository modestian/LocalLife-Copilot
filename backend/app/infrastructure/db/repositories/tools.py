"""Append-only SQLAlchemy audit writer for controlled tool calls."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infrastructure.db.models.governance import AuditLog


class SQLAlchemyToolAuditRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append_tool_audit(
        self,
        *,
        actor_id: UUID,
        request_id: str,
        resource_id: UUID | None,
        result: str,
        summary: dict[str, object],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                AuditLog(
                    actor_id=actor_id,
                    action="TOOL_CALL",
                    resource_type="TOOL",
                    resource_id=resource_id,
                    request_id=request_id[:128] or "internal",
                    result=result,
                    after_summary_json=summary,
                )
            )
