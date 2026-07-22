"""Acceptance tests for TK-302-03 controlled tool execution."""

import asyncio
from dataclasses import dataclass, field
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel, ConfigDict

from app.agents.tools import (
    ToolArgumentsInvalid,
    ToolAuditUnavailable,
    ToolAuthorizationDenied,
    ToolExecutionContext,
    ToolExecutionFailed,
    ToolExecutor,
    ToolNotRegistered,
    ToolRegistry,
    ToolRisk,
    ToolSpec,
    ToolTimedOut,
)
from app.application.authorization import (
    AuthorizationPrincipal,
    PermissionRule,
    ResourceGrantRule,
    ResourceType,
    RoleInfo,
)


class MerchantArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    merchant_id: UUID
    limit: int
    api_key: str


class UnsafeArgs(BaseModel):
    value: str


@dataclass
class RecordingAudit:
    rows: list[dict[str, object]] = field(default_factory=list)

    async def append_tool_audit(self, **values: object) -> None:
        self.rows.append(values)


class BrokenAudit:
    async def append_tool_audit(self, **_values: object) -> None:
        raise RuntimeError("database unavailable")


def _principal(
    *,
    permission: bool = True,
    merchant_id: UUID | None = None,
    grant: bool = True,
) -> AuthorizationPrincipal:
    permissions = (PermissionRule("merchant.read", "MERCHANT", "READ"),) if permission else ()
    grants = (
        (ResourceGrantRule(ResourceType.MERCHANT, merchant_id, "READ"),)
        if merchant_id is not None and grant
        else ()
    )
    return AuthorizationPrincipal(
        user_id=uuid4(),
        username="tool-user",
        display_name="Tool User",
        email=None,
        department_id=None,
        roles=(RoleInfo("USER", "User"),),
        permissions=permissions,
        resource_grants=grants,
    )


def _spec(handler, *, timeout: float = 1.0) -> ToolSpec:
    return ToolSpec(
        name="merchant.reviews",
        description="Read an authorized merchant review summary",
        args_schema=MerchantArgs,
        handler=handler,
        permission_resource="MERCHANT",
        permission_action="READ",
        timeout_seconds=timeout,
        risk=ToolRisk.LOW,
        resource_id_field="merchant_id",
    )


def _context(principal: AuthorizationPrincipal) -> ToolExecutionContext:
    return ToolExecutionContext(principal.user_id, "req-tool-1", uuid4())


def test_registry_rejects_duplicates_sync_handlers_and_permissive_schemas() -> None:
    async def handler(_arguments, _context):
        return None

    registry = ToolRegistry()
    spec = _spec(handler)
    registry.register(spec)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(spec)
    with pytest.raises(ValueError, match="extra='forbid'"):
        ToolSpec(
            name="unsafe.schema",
            description="unsafe schema",
            args_schema=UnsafeArgs,
            handler=handler,
            permission_resource="MERCHANT",
            permission_action="READ",
        )
    with pytest.raises(TypeError, match="must be async"):
        ToolSpec(
            name="unsafe.sync",
            description="sync handler",
            args_schema=MerchantArgs,
            handler=lambda _arguments, _context: None,  # type: ignore[arg-type]
            permission_resource="MERCHANT",
            permission_action="READ",
        )

    descriptor = registry.describe()[0]
    assert descriptor.name == "merchant.reviews"
    assert descriptor.args_schema["additionalProperties"] is False


async def test_valid_registered_authorized_call_executes_and_is_audited_without_values() -> None:
    merchant_id = uuid4()
    principal = _principal(merchant_id=merchant_id)
    received = []

    async def handler(arguments, context):
        received.append((arguments, context))
        return {"count": arguments.limit}

    registry = ToolRegistry()
    registry.register(_spec(handler))
    audit = RecordingAudit()

    result = await ToolExecutor(registry, audit).invoke(
        "merchant.reviews",
        {"merchant_id": merchant_id, "limit": 3, "api_key": "super-secret-key"},
        principal=principal,
        context=_context(principal),
    )

    assert result == {"count": 3}
    assert received[0][0].merchant_id == merchant_id
    assert received[0][1].actor_id == principal.user_id
    assert audit.rows[0]["result"] == "SUCCEEDED"
    assert audit.rows[0]["resource_id"] == merchant_id
    summary = audit.rows[0]["summary"]
    assert summary["tool_name"] == "merchant.reviews"
    assert summary["argument_fields"] == ["api_key", "limit", "merchant_id"]
    assert "super-secret-key" not in str(summary)
    assert len(summary["arguments_sha256"]) == 64


async def test_unregistered_invalid_and_unauthorized_calls_are_blocked_and_audited() -> None:
    merchant_id = uuid4()
    principal = _principal(merchant_id=merchant_id)

    async def handler(_arguments, _context):
        raise AssertionError("blocked calls must not execute")

    registry = ToolRegistry()
    registry.register(_spec(handler))
    audit = RecordingAudit()
    executor = ToolExecutor(registry, audit)

    with pytest.raises(ToolNotRegistered):
        await executor.invoke(
            "system.shell",
            {},
            principal=principal,
            context=_context(principal),
        )
    with pytest.raises(ToolArgumentsInvalid) as invalid:
        await executor.invoke(
            "merchant.reviews",
            {
                "merchant_id": merchant_id,
                "limit": "3",
                "api_key": "secret",
                "command": "whoami",
            },
            principal=principal,
            context=_context(principal),
        )
    assert {error["field"] for error in invalid.value.errors} == {"limit", "command"}
    with pytest.raises(ToolAuthorizationDenied):
        await executor.invoke(
            "merchant.reviews",
            {"merchant_id": merchant_id, "limit": 3, "api_key": "secret"},
            principal=_principal(permission=False),
            context=_context(principal),
        )
    with pytest.raises(ToolAuthorizationDenied):
        await executor.invoke(
            "merchant.reviews",
            {"merchant_id": merchant_id, "limit": 3, "api_key": "secret"},
            principal=_principal(merchant_id=merchant_id, grant=False),
            context=_context(principal),
        )

    assert [row["result"] for row in audit.rows] == [
        "BLOCKED",
        "BLOCKED",
        "BLOCKED",
        "BLOCKED",
    ]
    assert [row["summary"]["error_code"] for row in audit.rows] == [
        "TOOL_NOT_REGISTERED",
        "TOOL_ARGUMENTS_INVALID",
        "TOOL_AUTHORIZATION_DENIED",
        "TOOL_AUTHORIZATION_DENIED",
    ]
    assert "secret" not in str(audit.rows)


async def test_timeout_cancels_handler_and_records_failed_call() -> None:
    merchant_id = uuid4()
    principal = _principal(merchant_id=merchant_id)
    cancelled = asyncio.Event()

    async def handler(_arguments, _context):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.set()

    registry = ToolRegistry()
    registry.register(_spec(handler, timeout=0.01))
    audit = RecordingAudit()

    with pytest.raises(ToolTimedOut):
        await ToolExecutor(registry, audit).invoke(
            "merchant.reviews",
            {"merchant_id": merchant_id, "limit": 3, "api_key": "secret"},
            principal=principal,
            context=_context(principal),
        )

    assert cancelled.is_set()
    assert audit.rows[0]["result"] == "FAILED"
    assert audit.rows[0]["summary"]["error_code"] == "TOOL_TIMEOUT"


async def test_handler_failure_is_wrapped_and_audit_failure_fails_closed() -> None:
    merchant_id = uuid4()
    principal = _principal(merchant_id=merchant_id)

    async def handler(_arguments, _context):
        raise RuntimeError("internal details and secret")

    registry = ToolRegistry()
    registry.register(_spec(handler))
    audit = RecordingAudit()
    arguments = {"merchant_id": merchant_id, "limit": 3, "api_key": "secret"}

    with pytest.raises(ToolExecutionFailed, match="registered tool execution failed"):
        await ToolExecutor(registry, audit).invoke(
            "merchant.reviews",
            arguments,
            principal=principal,
            context=_context(principal),
        )
    assert "internal details" not in str(audit.rows)
    assert audit.rows[0]["summary"]["error_code"] == "TOOL_EXECUTION_FAILED"

    with pytest.raises(ToolAuditUnavailable):
        await ToolExecutor(registry, BrokenAudit()).invoke(
            "merchant.reviews",
            arguments,
            principal=principal,
            context=_context(principal),
        )
