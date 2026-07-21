"""Read-only SQLAlchemy audit log queries."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.audit import AuditFilter, AuditRecord
from app.infrastructure.db.models.governance import AuditLog


class SQLAlchemyAuditRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def query(
        self,
        filters: AuditFilter,
        *,
        limit: int,
        cursor: tuple[datetime, UUID] | None,
    ) -> list[AuditRecord]:
        conditions = []
        if filters.actor_id is not None:
            conditions.append(AuditLog.actor_id == filters.actor_id)
        if filters.module is not None:
            conditions.append(AuditLog.resource_type == filters.module)
        if filters.start_time is not None:
            conditions.append(AuditLog.created_at >= filters.start_time)
        if filters.end_time is not None:
            conditions.append(AuditLog.created_at <= filters.end_time)
        if filters.result is not None:
            conditions.append(AuditLog.result == filters.result)
        if cursor is not None:
            cursor_time, cursor_id = cursor
            conditions.append(
                or_(
                    AuditLog.created_at < cursor_time,
                    and_(AuditLog.created_at == cursor_time, AuditLog.id < cursor_id),
                )
            )
        statement = select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        if conditions:
            statement = statement.where(*conditions)
        async with self._session_factory() as session:
            rows = (await session.scalars(statement.limit(limit))).all()
        return [_to_record(row) for row in rows]


def _to_record(row: AuditLog) -> AuditRecord:
    return AuditRecord(
        id=row.id,
        actor_id=row.actor_id,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        request_id=row.request_id,
        ip_address=row.ip_address,
        result=row.result,
        before_summary=row.before_summary_json,
        after_summary=row.after_summary_json,
        created_at=row.created_at,
    )
