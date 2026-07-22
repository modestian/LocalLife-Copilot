"""Whitelisted, permission-aware tool execution for TK-302-03."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ValidationError

from app.application.authorization import AuthorizationDenied, AuthorizationPrincipal, ResourceType

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_MAX_TIMEOUT_SECONDS = 30.0


class ToolRisk(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ToolCallError(RuntimeError):
    """Safe base error returned by the controlled tool layer."""

    code = "TOOL_CALL_FAILED"


class ToolNotRegistered(ToolCallError):
    code = "TOOL_NOT_REGISTERED"


class ToolArgumentsInvalid(ToolCallError):
    code = "TOOL_ARGUMENTS_INVALID"

    def __init__(self, errors: tuple[dict[str, object], ...]) -> None:
        super().__init__("tool arguments do not match args_schema")
        self.errors = errors


class ToolAuthorizationDenied(ToolCallError):
    code = "TOOL_AUTHORIZATION_DENIED"


class ToolTimedOut(ToolCallError):
    code = "TOOL_TIMEOUT"


class ToolExecutionFailed(ToolCallError):
    code = "TOOL_EXECUTION_FAILED"


class ToolAuditUnavailable(ToolCallError):
    code = "TOOL_AUDIT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Least-privilege context supplied to a registered handler."""

    actor_id: UUID
    request_id: str
    conversation_id: UUID | None = None


type ToolHandler = Callable[[BaseModel, ToolExecutionContext], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    args_schema: type[BaseModel]
    handler: ToolHandler
    permission_resource: str
    permission_action: str
    timeout_seconds: float = 10.0
    risk: ToolRisk = ToolRisk.LOW
    resource_id_field: str | None = None

    def __post_init__(self) -> None:
        if not _TOOL_NAME.fullmatch(self.name):
            raise ValueError("tool name must be a lowercase dotted identifier")
        if not self.description.strip():
            raise ValueError("tool description must not be blank")
        if not inspect.isclass(self.args_schema) or not issubclass(self.args_schema, BaseModel):
            raise TypeError("args_schema must be a Pydantic BaseModel class")
        if self.args_schema.model_config.get("extra") != "forbid":
            raise ValueError("args_schema must configure extra='forbid'")
        if not inspect.iscoroutinefunction(self.handler):
            raise TypeError("tool handler must be async")
        if not self.permission_resource.strip() or not self.permission_action.strip():
            raise ValueError("tool permission resource and action must not be blank")
        if not 0 < self.timeout_seconds <= _MAX_TIMEOUT_SECONDS:
            raise ValueError("tool timeout must be greater than 0 and at most 30 seconds")
        if self.resource_id_field is not None:
            if self.resource_id_field not in self.args_schema.model_fields:
                raise ValueError("resource_id_field must exist in args_schema")
            try:
                ResourceType(self.permission_resource.strip().upper())
            except ValueError as exc:
                raise ValueError(
                    "resource-scoped tools must use a supported authorization resource type"
                ) from exc


@dataclass(frozen=True, slots=True)
class ToolDescriptor:
    name: str
    description: str
    args_schema: dict[str, object]
    risk: ToolRisk
    timeout_seconds: float


class ToolRegistry:
    """In-memory whitelist; registration never performs dynamic imports or evaluation."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def describe(self) -> tuple[ToolDescriptor, ...]:
        return tuple(
            ToolDescriptor(
                name=spec.name,
                description=spec.description,
                args_schema=spec.args_schema.model_json_schema(),
                risk=spec.risk,
                timeout_seconds=spec.timeout_seconds,
            )
            for spec in sorted(self._tools.values(), key=lambda value: value.name)
        )


class ToolAuditRepository(Protocol):
    async def append_tool_audit(
        self,
        *,
        actor_id: UUID,
        request_id: str,
        resource_id: UUID | None,
        result: str,
        summary: dict[str, object],
    ) -> None: ...


class ToolExecutor:
    """Validate, authorize, time-limit and audit one registered tool invocation."""

    def __init__(self, registry: ToolRegistry, audit_repository: ToolAuditRepository) -> None:
        self._registry = registry
        self._audit = audit_repository

    async def invoke(
        self,
        name: str,
        arguments: Mapping[str, object],
        *,
        principal: AuthorizationPrincipal,
        context: ToolExecutionContext,
    ) -> object:
        started = time.monotonic()
        spec = self._registry.get(name)
        if spec is None:
            error = ToolNotRegistered("tool is not registered")
            await self._record(
                context=context,
                resource_id=None,
                result="BLOCKED",
                summary=_audit_summary(name, arguments, started, error.code),
            )
            raise error

        try:
            validated = spec.args_schema.model_validate(dict(arguments), strict=True)
        except (TypeError, ValidationError) as exc:
            error = ToolArgumentsInvalid(_validation_errors(exc))
            await self._record(
                context=context,
                resource_id=None,
                result="BLOCKED",
                summary=_audit_summary(name, arguments, started, error.code, spec),
            )
            raise error from exc

        try:
            resource_id = _resource_id(spec, validated)
        except ToolArgumentsInvalid as error:
            await self._record(
                context=context,
                resource_id=None,
                result="BLOCKED",
                summary=_audit_summary(name, arguments, started, error.code, spec),
            )
            raise
        try:
            principal.require_permission(spec.permission_resource, spec.permission_action)
            if resource_id is not None:
                principal.require_resource_access(
                    spec.permission_resource, resource_id, spec.permission_action
                )
        except AuthorizationDenied as exc:
            error = ToolAuthorizationDenied("tool permission denied")
            await self._record(
                context=context,
                resource_id=resource_id,
                result="BLOCKED",
                summary=_audit_summary(name, arguments, started, error.code, spec),
            )
            raise error from exc

        try:
            async with asyncio.timeout(spec.timeout_seconds):
                result = await spec.handler(validated, context)
        except TimeoutError as exc:
            error = ToolTimedOut("tool execution timed out")
            await self._record(
                context=context,
                resource_id=resource_id,
                result="FAILED",
                summary=_audit_summary(name, arguments, started, error.code, spec),
            )
            raise error from exc
        except asyncio.CancelledError:
            await self._record(
                context=context,
                resource_id=resource_id,
                result="FAILED",
                summary=_audit_summary(name, arguments, started, "TOOL_CANCELLED", spec),
            )
            raise
        except Exception as exc:
            error = ToolExecutionFailed("registered tool execution failed")
            await self._record(
                context=context,
                resource_id=resource_id,
                result="FAILED",
                summary=_audit_summary(name, arguments, started, error.code, spec),
            )
            raise error from exc

        await self._record(
            context=context,
            resource_id=resource_id,
            result="SUCCEEDED",
            summary=_audit_summary(name, arguments, started, None, spec),
        )
        return result

    async def _record(
        self,
        *,
        context: ToolExecutionContext,
        resource_id: UUID | None,
        result: str,
        summary: dict[str, object],
    ) -> None:
        try:
            await self._audit.append_tool_audit(
                actor_id=context.actor_id,
                request_id=context.request_id,
                resource_id=resource_id,
                result=result,
                summary=summary,
            )
        except Exception as exc:
            raise ToolAuditUnavailable("tool audit could not be persisted") from exc


def _resource_id(spec: ToolSpec, arguments: BaseModel) -> UUID | None:
    if spec.resource_id_field is None:
        return None
    value = getattr(arguments, spec.resource_id_field)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ToolArgumentsInvalid(
            ({"field": spec.resource_id_field, "reason": "uuid_parsing"},)
        ) from exc


def _validation_errors(exc: TypeError | ValidationError) -> tuple[dict[str, object], ...]:
    if isinstance(exc, TypeError):
        return ({"field": "arguments", "reason": "mapping_type"},)
    return tuple(
        {
            "field": ".".join(str(part) for part in error["loc"]),
            "reason": error["type"],
        }
        for error in exc.errors(include_url=False, include_input=False)
    )


def _audit_summary(
    name: str,
    arguments: Mapping[str, object],
    started: float,
    error_code: str | None,
    spec: ToolSpec | None = None,
) -> dict[str, object]:
    try:
        canonical = json.dumps(arguments, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        canonical = repr(sorted(str(key) for key in arguments))
    summary: dict[str, object] = {
        "tool_name": name[:128],
        "argument_fields": sorted(str(key)[:128] for key in arguments),
        "arguments_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "latency_ms": max(0, round((time.monotonic() - started) * 1000)),
    }
    if spec is not None:
        summary.update(
            {
                "risk": spec.risk.value,
                "timeout_ms": round(spec.timeout_seconds * 1000),
                "args_schema": spec.args_schema.__name__,
            }
        )
    if error_code is not None:
        summary["error_code"] = error_code
    return summary
