"""Administrative prompt and model governance APIs for ST-103."""

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.governance import (
    DeploymentRequest,
    GovernanceResourceNotFound,
    InvalidLifecycleTransition,
    ModelVersionStatus,
)
from app.core.api import get_request_id, success_response
from app.core.errors import AppError
from app.infrastructure.db.repositories.governance import SQLAlchemyGovernanceRepository

router = APIRouter(tags=["governance"])


class PromptCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    scene: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=1000)
    content: str = Field(min_length=1, max_length=1_000_000)
    variables: dict[str, object] = Field(default_factory=dict)


class OperationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = Field(min_length=1, max_length=1000)


class ModelCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    task_type: str = Field(min_length=1, max_length=64)
    provider: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=64)
    base_model_ref: str = Field(min_length=1, max_length=500)
    adapter_uri: str = Field(min_length=1, max_length=1000)
    artifact_sha256: str = Field(pattern=r"(?i)^[0-9a-f]{64}$")
    dimension: int | None = Field(default=None, gt=0)
    labels: list[str] | None = None
    metrics: dict[str, object] | None = None


class ModelStatusDTO(OperationDTO):
    status: Literal["EVALUATED", "APPROVED", "REJECTED", "ARCHIVED"]


class ModelDeployDTO(OperationDTO):
    scene: str = Field(min_length=1, max_length=64)
    environment: str = Field(min_length=1, max_length=32)
    traffic_percent: int = Field(ge=1, le=100)


class ModelRollbackDTO(OperationDTO):
    scene: str = Field(min_length=1, max_length=64)
    environment: str = Field(min_length=1, max_length=32)


def get_governance_repository(request: Request) -> SQLAlchemyGovernanceRepository:
    repository: SQLAlchemyGovernanceRepository | None = getattr(
        request.app.state, "governance_repository", None
    )
    if repository is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "治理服务尚未配置")
    return repository


GovernanceDependency = Annotated[SQLAlchemyGovernanceRepository, Depends(get_governance_repository)]


def _require_admin(principal: CurrentPrincipal) -> None:
    if not principal.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "仅平台管理员可以执行治理操作")


def _prompt_data(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "definition_id": str(row.prompt_definition_id),
        "version_no": row.version_no,
        "content": row.content,
        "variables": dict(row.variables_json),
        "content_hash": row.content_hash,
        "status": _value(row.status),
        "created_by": str(row.created_by),
        "created_at": row.created_at.isoformat(),
        "published_by": str(row.published_by) if row.published_by else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "publication_action": row.publication_action,
        "publication_result": row.publication_result,
    }


def _model_data(row: Any, definition: Any | None = None) -> dict[str, Any]:
    data = {
        "id": str(row.id),
        "definition_id": str(row.model_definition_id),
        "version": row.version,
        "base_model_ref": row.base_model_ref,
        "adapter_uri": row.adapter_uri,
        "artifact_sha256": row.artifact_sha256,
        "dimension": row.dimension,
        "labels": row.labels_json,
        "metrics": row.metrics_json,
        "status": _value(row.status),
        "created_by": str(row.created_by),
        "created_at": row.created_at.isoformat(),
    }
    if definition is not None:
        data["code"] = definition.code
        data["name"] = definition.name
        data["task_type"] = definition.task_type
        data["provider"] = definition.provider
    return data


def _deployment_data(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "model_version_id": str(row.model_version_id),
        "scene": row.scene,
        "environment": row.environment,
        "traffic_percent": row.traffic_percent,
        "action": _value(row.action),
        "status": _value(row.status),
        "result": row.result,
        "deployed_by": str(row.deployed_by),
        "reason": row.reason,
        "created_at": row.created_at.isoformat(),
    }


@router.post("/prompts", status_code=201)
async def create_prompt(
    request: Request,
    body: PromptCreateDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.create_prompt(
            **body.model_dump(),
            created_by=principal.user_id,
            request_id=get_request_id(request),
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository, request, principal.user_id, "PROMPT_VERSION_CREATED", "PROMPT", None, exc
        ) from exc
    return success_response(request, _prompt_data(row), message="created")


@router.post("/prompts/{prompt_version_id}/publish")
async def publish_prompt(
    request: Request,
    prompt_version_id: UUID,
    body: OperationDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.publish_prompt(
            prompt_version_id,
            published_by=principal.user_id,
            request_id=get_request_id(request),
            reason=body.reason,
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository,
            request,
            principal.user_id,
            "PROMPT_PUBLISH",
            "PROMPT",
            prompt_version_id,
            exc,
        ) from exc
    return success_response(request, _prompt_data(row), message="published")


@router.post("/prompts/{prompt_version_id}/rollback", status_code=201)
async def rollback_prompt(
    request: Request,
    prompt_version_id: UUID,
    body: OperationDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.rollback_prompt(
            prompt_version_id,
            rolled_back_by=principal.user_id,
            request_id=get_request_id(request),
            reason=body.reason,
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository,
            request,
            principal.user_id,
            "PROMPT_ROLLBACK",
            "PROMPT",
            prompt_version_id,
            exc,
        ) from exc
    return success_response(request, _prompt_data(row), message="rolled back")


@router.get("/models")
async def list_models(
    request: Request,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    rows = await repository.list_models()
    return success_response(
        request, {"items": [_model_data(version, definition) for version, definition in rows]}
    )


@router.post("/models", status_code=201)
async def register_model(
    request: Request,
    body: ModelCreateDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.register_model(
            **body.model_dump(),
            created_by=principal.user_id,
            request_id=get_request_id(request),
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository, request, principal.user_id, "MODEL_VERSION_REGISTERED", "MODEL", None, exc
        ) from exc
    return success_response(request, _model_data(row), message="registered")


@router.post("/models/{model_version_id}/status")
async def transition_model(
    request: Request,
    model_version_id: UUID,
    body: ModelStatusDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.transition_model(
            model_version_id,
            ModelVersionStatus(body.status),
            actor_id=principal.user_id,
            request_id=get_request_id(request),
            reason=body.reason,
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository,
            request,
            principal.user_id,
            "MODEL_STATUS_TRANSITION",
            "MODEL",
            model_version_id,
            exc,
        ) from exc
    return success_response(request, _model_data(row), message="transitioned")


@router.post("/models/{model_version_id}/deploy", status_code=201)
async def deploy_model(
    request: Request,
    model_version_id: UUID,
    body: ModelDeployDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    operation = "MODEL_FULL" if body.traffic_percent == 100 else "MODEL_CANARY"
    try:
        row = await repository.deploy_model(
            DeploymentRequest(
                model_version_id=model_version_id,
                scene=body.scene,
                environment=body.environment,
                traffic_percent=body.traffic_percent,
                deployed_by=principal.user_id,
                reason=body.reason,
                request_id=get_request_id(request),
            )
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository,
            request,
            principal.user_id,
            operation,
            "MODEL",
            model_version_id,
            exc,
        ) from exc
    return success_response(request, _deployment_data(row), message="deployed")


@router.post("/models/{model_version_id}/rollback", status_code=201)
async def rollback_model(
    request: Request,
    model_version_id: UUID,
    body: ModelRollbackDTO,
    principal: CurrentPrincipal,
    repository: GovernanceDependency,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await repository.rollback_model(
            scene=body.scene,
            environment=body.environment,
            target_model_version_id=model_version_id,
            deployed_by=principal.user_id,
            reason=body.reason,
            request_id=get_request_id(request),
        )
    except (ValueError, IntegrityError) as exc:
        raise await _operation_error(
            repository,
            request,
            principal.user_id,
            "MODEL_ROLLBACK",
            "MODEL",
            model_version_id,
            exc,
        ) from exc
    return success_response(request, _deployment_data(row), message="rolled back")


async def _operation_error(
    repository: SQLAlchemyGovernanceRepository,
    request: Request,
    actor_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    exc: Exception,
) -> AppError:
    if isinstance(exc, GovernanceResourceNotFound):
        status_code, code = 404, "GOVERNANCE_NOT_FOUND"
    elif isinstance(exc, InvalidLifecycleTransition | IntegrityError):
        status_code, code = 409, "GOVERNANCE_CONFLICT"
    else:
        status_code, code = 422, "INVALID_GOVERNANCE_OPERATION"
    try:
        await repository.append_operation_audit(
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=get_request_id(request),
            result="FAILED",
            summary={"error_code": code},
        )
    except Exception:
        # Preserve the original business error when the audit store itself is unavailable.
        pass
    message = (
        "governance resource conflicts with existing state"
        if isinstance(exc, IntegrityError)
        else str(exc)
    )
    return AppError(status_code, code, message)


def _value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value
