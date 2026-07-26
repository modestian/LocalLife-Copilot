"""SQLAlchemy persistence for sensitive-word rules and rejection audits."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.content_safety import (
    ContentDirection,
    SensitiveMatchType,
    SensitiveRuleRecord,
    SensitiveRuleScope,
)
from app.infrastructure.db.models.governance import AuditLog, SensitiveWordRule


class SQLAlchemyContentSafetyRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_rule(
        self,
        *,
        word: str,
        normalized_word: str,
        scope: SensitiveRuleScope,
        match_type: SensitiveMatchType,
        severity: str,
        created_by: UUID,
    ) -> SensitiveRuleRecord:
        async with self._session_factory() as session, session.begin():
            previous = (
                await session.scalars(
                    select(SensitiveWordRule)
                    .where(
                        SensitiveWordRule.normalized_word == normalized_word,
                        SensitiveWordRule.scope == scope,
                    )
                    .with_for_update()
                )
            ).all()
            latest = max((row.version_no for row in previous), default=0)
            for row in previous:
                row.enabled = False
            rule = SensitiveWordRule(
                word=word,
                normalized_word=normalized_word,
                scope=scope,
                match_type=match_type,
                severity=severity,
                version_no=latest + 1,
                enabled=True,
                created_by=created_by,
            )
            session.add(rule)
            await session.flush()
            return _to_record(rule)

    async def list_rules(self, *, enabled_only: bool = False) -> list[SensitiveRuleRecord]:
        async with self._session_factory() as session:
            statement = select(SensitiveWordRule).order_by(
                SensitiveWordRule.normalized_word, SensitiveWordRule.version_no.desc()
            )
            if enabled_only:
                statement = statement.where(SensitiveWordRule.enabled.is_(True))
            return [_to_record(row) for row in (await session.scalars(statement)).all()]

    async def disable_rule(self, *, rule_id: UUID) -> SensitiveRuleRecord | None:
        async with self._session_factory() as session, session.begin():
            row = await session.get(SensitiveWordRule, rule_id, with_for_update=True)
            if row is None:
                return None
            row.enabled = False
            await session.flush()
            return _to_record(row)

    async def append_rejection_audit(
        self,
        *,
        actor_id: UUID,
        direction: ContentDirection,
        request_id: str,
        conversation_id: UUID | None,
        content_sha256: str,
        content_length: int,
        matched_rule_ids: tuple[UUID, ...],
    ) -> None:
        async with self._session_factory() as session, session.begin():
            session.add(
                AuditLog(
                    actor_id=actor_id,
                    action=f"SENSITIVE_{direction.value}_REJECTED",
                    resource_type="CONTENT_SAFETY",
                    resource_id=conversation_id,
                    request_id=request_id[:128],
                    result="BLOCKED",
                    after_summary_json={
                        "direction": direction.value,
                        "content_sha256": content_sha256,
                        "content_length": content_length,
                        "matched_rule_ids": [str(rule_id) for rule_id in matched_rule_ids],
                    },
                )
            )


def _to_record(row: SensitiveWordRule) -> SensitiveRuleRecord:
    return SensitiveRuleRecord(
        id=row.id,
        word=row.word,
        normalized_word=row.normalized_word,
        scope=SensitiveRuleScope(row.scope),
        match_type=SensitiveMatchType(row.match_type),
        severity=row.severity,
        version_no=row.version_no,
        enabled=row.enabled,
    )
