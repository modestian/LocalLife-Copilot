"""TK-103-04 concurrency, append-only audit and log-redaction gates."""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, make_transient_to_detached

from app.api.observability import audit_router
from app.core.config import Settings
from app.core.ids import uuid7
from app.core.observability import JsonLogFormatter, redact_sensitive_data
from app.infrastructure.db.models.governance import (
    AuditLog,
    PromptDefinition,
    PromptVersion,
    _protect_audit_log,
)
from app.infrastructure.db.models.identity import User
from app.infrastructure.db.repositories.governance import SQLAlchemyGovernanceRepository


class _Rows:
    def __init__(self, rows: list[PromptVersion]) -> None:
        self._rows = rows

    def all(self) -> list[PromptVersion]:
        return self._rows


class _ConcurrentPromptState:
    def __init__(self) -> None:
        self.definition_id = uuid7()
        self.definition = object()
        self.lock = asyncio.Lock()
        self.versions = {
            version_id: PromptVersion(
                id=version_id,
                prompt_definition_id=self.definition_id,
                version_no=index,
                content=f"draft-{index}",
                variables_json={},
                status="DRAFT",
                content_hash=str(index) * 64,
                created_by=uuid7(),
            )
            for index, version_id in enumerate((uuid7(), uuid7()), start=1)
        }


class _FakeTransaction:
    def __init__(self, session: "_FakeConcurrentSession") -> None:
        self._session = session

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        del args
        if self._session.holds_definition_lock:
            self._session.holds_definition_lock = False
            self._session.state.lock.release()


class _FakeConcurrentSession:
    def __init__(self, state: _ConcurrentPromptState) -> None:
        self.state = state
        self.holds_definition_lock = False

    async def __aenter__(self) -> "_FakeConcurrentSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    def begin(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def scalar(self, statement: Any) -> object | None:
        description = statement.column_descriptions[0]
        parameters = statement.compile().params
        if description["name"] == "prompt_definition_id":
            await asyncio.sleep(0)
            return self.state.definition_id
        if description["entity"] is PromptDefinition:
            await self.state.lock.acquire()
            self.holds_definition_lock = True
            return self.state.definition
        if description["entity"] is PromptVersion:
            target_id = parameters["id_1"]
            return self.state.versions[target_id]
        raise AssertionError("unexpected publication query")

    async def scalars(self, statement: Any) -> _Rows:
        del statement
        return _Rows([row for row in self.state.versions.values() if row.status == "PUBLISHED"])

    async def flush(self) -> None:
        await asyncio.sleep(0)


class _FakeConcurrentSessionFactory:
    def __init__(self, state: _ConcurrentPromptState) -> None:
        self._state = state

    def __call__(self) -> _FakeConcurrentSession:
        return _FakeConcurrentSession(self._state)


@pytest.mark.asyncio
async def test_repository_serializes_concurrent_publication_of_distinct_drafts() -> None:
    """Exercise the real repository flow with deterministic row-lock semantics."""
    state = _ConcurrentPromptState()
    repository = SQLAlchemyGovernanceRepository(_FakeConcurrentSessionFactory(state))  # type: ignore[arg-type]
    first_id, second_id = state.versions
    actor_id = uuid7()

    await asyncio.gather(
        repository.publish_prompt(first_id, published_by=actor_id),
        repository.publish_prompt(second_id, published_by=actor_id),
    )

    versions = list(state.versions.values())
    assert sum(row.status == "PUBLISHED" for row in versions) == 1
    assert sorted(row.status for row in versions) == ["ARCHIVED", "PUBLISHED"]
    assert all(row.published_by == actor_id for row in versions)


@pytest.mark.skipif(
    os.getenv("ST103_MYSQL_INTEGRATION") != "1",
    reason="set ST103_MYSQL_INTEGRATION=1 with migrated MySQL available",
)
@pytest.mark.asyncio
async def test_concurrent_prompt_publications_leave_exactly_one_published_version() -> None:
    """The definition-row lock must serialize publication of two distinct drafts."""
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    repository = SQLAlchemyGovernanceRepository(session_factory)
    suffix = uuid7().hex
    actor_id = uuid7()
    definition_id = uuid7()
    version_ids: list[UUID] = []
    try:
        async with session_factory() as session, session.begin():
            session.add(
                User(
                    id=actor_id,
                    username=f"st103-{suffix}",
                    normalized_username=f"st103-{suffix}",
                    password_hash="integration-test-only",
                    display_name="ST-103 integration actor",
                )
            )
            session.add(
                PromptDefinition(
                    id=definition_id,
                    code=f"st103-{suffix}",
                    name="ST-103 concurrent prompt",
                    scene="integration",
                )
            )
        first = await repository.create_prompt_version(
            prompt_definition_id=definition_id,
            content="first",
            variables={},
            created_by=actor_id,
        )
        second = await repository.create_prompt_version(
            prompt_definition_id=definition_id,
            content="second",
            variables={},
            created_by=actor_id,
        )
        version_ids = [first.id, second.id]

        await asyncio.gather(
            repository.publish_prompt(first.id, published_by=actor_id),
            repository.publish_prompt(second.id, published_by=actor_id),
        )

        async with session_factory() as session:
            versions = (
                await session.scalars(
                    select(PromptVersion).where(PromptVersion.prompt_definition_id == definition_id)
                )
            ).all()
        assert sum(row.status == "PUBLISHED" for row in versions) == 1
        assert sorted(row.status for row in versions) == ["ARCHIVED", "PUBLISHED"]
        assert all(row.published_by == actor_id for row in versions)
    finally:
        async with session_factory() as session, session.begin():
            if version_ids:
                await session.execute(
                    delete(PromptVersion).where(PromptVersion.id.in_(version_ids))
                )
            await session.execute(
                delete(PromptDefinition).where(PromptDefinition.id == definition_id)
            )
            await session.execute(delete(User).where(User.id == actor_id))
        await engine.dispose()


def _detached_audit() -> AuditLog:
    row = AuditLog(
        id=uuid7(),
        actor_id=uuid7(),
        action="TEST",
        resource_type="GOVERNANCE",
        request_id="request-1",
        result="SUCCEEDED",
        after_summary_json={"version": 1},
        created_at=datetime(2026, 7, 21, 12, 0),
    )
    make_transient_to_detached(row)
    return row


def test_audit_model_rejects_update_after_persistence() -> None:
    row = _detached_audit()
    with Session() as session:
        session.add(row)
        row.result = "FAILED"
        with pytest.raises(ValueError, match="append-only"):
            _protect_audit_log(None, None, row)


def test_audit_model_registers_update_and_delete_guards() -> None:
    assert event.contains(AuditLog, "before_update", _protect_audit_log)
    assert event.contains(AuditLog, "before_delete", _protect_audit_log)


def test_audit_business_router_exposes_get_only() -> None:
    audit_routes = [route for route in audit_router.routes if route.path == "/audit-logs"]
    assert len(audit_routes) == 1
    assert audit_routes[0].methods == {"GET"}


@pytest.mark.parametrize(
    ("message", "secret"),
    [
        ('credentials={"password":"hunter 2"}', "hunter 2"),
        ("Authorization: Bearer abc.def-123", "abc.def-123"),
        ("access_token=token-value-123", "token-value-123"),
        ("mysql+pymysql://service:db-password@mysql/local_life", "db-password"),
        ("provider key sk-abcdefghijklmnopqrstuvwxyz", "sk-abcdefghijklmnopqrstuvwxyz"),
        ("aws key AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
        (
            "-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----",
            "private-material",
        ),
    ],
)
def test_json_log_message_never_contains_complete_secret(message: str, secret: str) -> None:
    record = logging.LogRecord("app.security", logging.ERROR, __file__, 1, message, (), None)
    payload = json.loads(JsonLogFormatter().format(record))

    assert secret not in payload["message"]
    assert "[REDACTED" in payload["message"]
    assert {"request_id", "user_id", "conversation_id", "latency_ms"} <= payload.keys()


def test_json_log_exception_redacts_database_password_and_token() -> None:
    try:
        raise RuntimeError(
            "connection mysql://worker:exception-password@mysql/db failed "
            "Authorization=Bearer exception-token"
        )
    except RuntimeError:
        exc_info = sys.exc_info()
    record = logging.LogRecord(
        "app.security", logging.ERROR, __file__, 1, "dependency failed", (), exc_info
    )

    payload = json.loads(JsonLogFormatter().format(record))

    assert "exception-password" not in payload["exception"]
    assert "exception-token" not in payload["exception"]
    assert "[REDACTED" in payload["exception"]


def test_nested_and_binary_log_details_are_redacted_without_source_mutation() -> None:
    source = {
        "nested": {"refresh_token": "nested-token"},
        "blob": b"password=binary-password",
    }

    redacted = redact_sensitive_data(source)

    assert redacted == {
        "nested": {"refresh_token": "[REDACTED]"},
        "blob": "password=[REDACTED]",
    }
    assert source["nested"]["refresh_token"] == "nested-token"  # type: ignore[index]
