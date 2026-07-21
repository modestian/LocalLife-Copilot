"""Acceptance tests for TK-103-02 sensitive-word checks and rejection auditing."""

from dataclasses import replace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.content_safety import get_content_safety_service, router
from app.api.dependencies.authorization import get_current_principal
from app.application.authorization import AuthorizationPrincipal, RoleInfo
from app.application.content_safety import (
    ContentDirection,
    ContentSafetyService,
    SensitiveMatchType,
    SensitiveRuleRecord,
    SensitiveRuleScope,
)
from app.core.api import install_api_contract
from app.core.config import Settings
from app.core.ids import uuid7
from app.infrastructure.db import Base
from app.infrastructure.db.models.governance import AuditLog, SensitiveWordRule


class InMemoryContentSafetyRepository:
    def __init__(self) -> None:
        self.rules: list[SensitiveRuleRecord] = []
        self.audits: list[dict[str, object]] = []

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
        del created_by
        matching = [
            rule
            for rule in self.rules
            if rule.normalized_word == normalized_word and rule.scope == scope
        ]
        self.rules = [
            replace(rule, enabled=False) if rule in matching else rule for rule in self.rules
        ]
        row = SensitiveRuleRecord(
            id=uuid7(),
            word=word,
            normalized_word=normalized_word,
            scope=scope,
            match_type=match_type,
            severity=severity,
            version_no=max((rule.version_no for rule in matching), default=0) + 1,
            enabled=True,
        )
        self.rules.append(row)
        return row

    async def list_rules(self, *, enabled_only: bool = False) -> list[SensitiveRuleRecord]:
        return [rule for rule in self.rules if rule.enabled or not enabled_only]

    async def append_rejection_audit(self, **values: object) -> None:
        self.audits.append(values)


@pytest.fixture
def safety_repo() -> InMemoryContentSafetyRepository:
    return InMemoryContentSafetyRepository()


@pytest.fixture
def safety_service(safety_repo: InMemoryContentSafetyRepository) -> ContentSafetyService:
    return ContentSafetyService(safety_repo)


def _principal(*, admin: bool = True) -> AuthorizationPrincipal:
    roles = (RoleInfo("PLATFORM_ADMIN", "Platform admin"),) if admin else ()
    return AuthorizationPrincipal(
        user_id=uuid7(),
        username="safety-user",
        display_name="Safety user",
        email=None,
        department_id=None,
        roles=roles,
        permissions=(),
        resource_grants=(),
    )


def _client(
    service: ContentSafetyService, *, principal: AuthorizationPrincipal | None = None
) -> TestClient:
    app = FastAPI()
    settings = Settings()
    install_api_contract(app, settings)
    app.include_router(router, prefix=settings.api_v1_prefix)
    app.dependency_overrides[get_content_safety_service] = lambda: service
    app.dependency_overrides[get_current_principal] = lambda: principal or _principal()
    return TestClient(app)


@pytest.mark.asyncio
async def test_rule_versions_replace_active_rule_without_losing_history(
    safety_service: ContentSafetyService, safety_repo: InMemoryContentSafetyRepository
) -> None:
    actor = uuid7()
    first = await safety_service.create_rule(
        word="受限词",
        scope=SensitiveRuleScope.BOTH,
        match_type=SensitiveMatchType.CONTAINS,
        severity="high",
        created_by=actor,
    )
    second = await safety_service.create_rule(
        word="受限词",
        scope=SensitiveRuleScope.BOTH,
        match_type=SensitiveMatchType.EXACT,
        severity="medium",
        created_by=actor,
    )

    assert first.version_no == 1
    assert second.version_no == 2
    assert len(safety_repo.rules) == 2
    assert safety_repo.rules[0].enabled is False
    assert safety_repo.rules[1].enabled is True


@pytest.mark.asyncio
async def test_input_match_is_normalized_blocked_and_audited_without_raw_content(
    safety_service: ContentSafetyService, safety_repo: InMemoryContentSafetyRepository
) -> None:
    actor = uuid7()
    await safety_service.create_rule(
        word="ＡＢＣ",
        scope=SensitiveRuleScope.INPUT,
        match_type=SensitiveMatchType.CONTAINS,
        severity="HIGH",
        created_by=actor,
    )

    result = await safety_service.check(
        content="please abc now",
        direction=ContentDirection.INPUT,
        actor_id=actor,
        request_id="req-input",
    )

    assert result.allowed is False
    assert result.decision == "BLOCK_INPUT"
    assert len(safety_repo.audits) == 1
    audit = safety_repo.audits[0]
    assert audit["direction"] is ContentDirection.INPUT
    assert audit["request_id"] == "req-input"
    assert audit["content_length"] == len("please abc now")
    assert audit["content_sha256"] != "please abc now"
    assert "content" not in audit


@pytest.mark.asyncio
async def test_output_match_stops_output_and_records_conversation(
    safety_service: ContentSafetyService, safety_repo: InMemoryContentSafetyRepository
) -> None:
    actor = uuid7()
    conversation_id = uuid7()
    await safety_service.create_rule(
        word="禁止输出",
        scope=SensitiveRuleScope.OUTPUT,
        match_type=SensitiveMatchType.CONTAINS,
        severity="HIGH",
        created_by=actor,
    )

    result = await safety_service.check(
        content="模型生成了禁止输出的内容",
        direction=ContentDirection.OUTPUT,
        actor_id=actor,
        request_id="req-output",
        conversation_id=conversation_id,
    )

    assert result.allowed is False
    assert result.decision == "STOP_OUTPUT"
    assert safety_repo.audits[0]["conversation_id"] == conversation_id


@pytest.mark.asyncio
async def test_direction_scope_and_exact_match_do_not_overblock(
    safety_service: ContentSafetyService, safety_repo: InMemoryContentSafetyRepository
) -> None:
    actor = uuid7()
    await safety_service.create_rule(
        word="only-this",
        scope=SensitiveRuleScope.INPUT,
        match_type=SensitiveMatchType.EXACT,
        severity="LOW",
        created_by=actor,
    )

    longer = await safety_service.check(
        content="prefix only-this suffix",
        direction=ContentDirection.INPUT,
        actor_id=actor,
        request_id="req-1",
    )
    output = await safety_service.check(
        content="only-this",
        direction=ContentDirection.OUTPUT,
        actor_id=actor,
        request_id="req-2",
    )

    assert longer.allowed is True
    assert output.allowed is True
    assert safety_repo.audits == []


def test_admin_can_create_and_list_versioned_sensitive_rules(
    safety_service: ContentSafetyService,
) -> None:
    with _client(safety_service) as client:
        created = client.post(
            "/api/v1/sensitive-words",
            json={"word": "受限词", "scope": "BOTH", "severity": "HIGH"},
        )
        listed = client.get("/api/v1/sensitive-words", params={"enabled_only": True})

    assert created.status_code == 201
    assert created.json()["data"]["version_no"] == 1
    assert listed.status_code == 200
    assert len(listed.json()["data"]["items"]) == 1


def test_non_admin_cannot_manage_sensitive_rules(safety_service: ContentSafetyService) -> None:
    with _client(safety_service, principal=_principal(admin=False)) as client:
        response = client.post("/api/v1/sensitive-words", json={"word": "受限词"})

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_detection_endpoint_rejects_input_after_audit(
    safety_service: ContentSafetyService, safety_repo: InMemoryContentSafetyRepository
) -> None:
    with _client(safety_service) as client:
        client.post("/api/v1/sensitive-words", json={"word": "blocked"})
        response = client.post(
            "/api/v1/content-safety/check",
            json={"content": "this is BLOCKED", "direction": "INPUT"},
            headers={"X-Request-ID": "safety-request"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "SENSITIVE_INPUT_REJECTED"
    assert safety_repo.audits[0]["request_id"] == "safety-request"


def test_detection_endpoint_stops_sensitive_output(
    safety_service: ContentSafetyService,
) -> None:
    with _client(safety_service) as client:
        client.post(
            "/api/v1/sensitive-words",
            json={"word": "unsafe", "scope": "OUTPUT"},
        )
        response = client.post(
            "/api/v1/content-safety/check",
            json={"content": "unsafe model output", "direction": "OUTPUT"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "SENSITIVE_OUTPUT_STOPPED"
    assert "unsafe model output" not in response.text


def test_content_safety_tables_and_constraints_are_registered() -> None:
    assert Base.metadata.tables["sensitive_word_rules"] is SensitiveWordRule.__table__
    assert Base.metadata.tables["audit_logs"] is AuditLog.__table__
    assert "uq_sensitive_rules_word_scope_version" in {
        constraint.name for constraint in SensitiveWordRule.__table__.constraints
    }
    assert {index.name for index in AuditLog.__table__.indexes} == {
        "ix_audit_logs_actor_created",
        "ix_audit_logs_resource_created",
        "ix_audit_logs_result_created",
    }
