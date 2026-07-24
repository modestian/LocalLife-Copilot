from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import ResourceScopeDenied, ResourceType, RolePermissionDenied
from app.application.knowledge import DocumentNotFound
from app.application.tasks import TaskStatus, can_retry, cancellation_target
from app.core.api import success_response
from app.core.errors import AppError
from app.infrastructure.db.models.knowledge import Document

router = APIRouter(prefix="/tasks", tags=["tasks"])


async def _visible_task(request: Request, principal: CurrentPrincipal, task_id: UUID):
    task = await request.app.state.task_repository.get(task_id)
    if task is None:
        raise AppError(404, "NOT_FOUND", "任务不存在")
    if task.resource_type == "DOCUMENT":
        try:
            knowledge_repository = request.app.state.knowledge_repository.scoped(principal)
            resource_id = await knowledge_repository.get_task_document_knowledge_base_id(
                task.resource_id
            )
        except DocumentNotFound as exc:
            raise AppError(404, "NOT_FOUND", "任务资源不存在") from exc
    elif task.resource_type == "KNOWLEDGE_BASE":
        resource_id = task.resource_id
    elif task.resource_type == "MERCHANT":
        try:
            principal.require_resource_access(ResourceType.MERCHANT, task.resource_id, "READ")
        except RolePermissionDenied as exc:
            raise AppError(403, "FORBIDDEN", "没有查询任务的角色权限") from exc
        except ResourceScopeDenied as exc:
            raise AppError(404, "NOT_FOUND", "任务不存在或无访问权限") from exc
        return task
    else:
        if not principal.is_platform_admin:
            raise AppError(404, "NOT_FOUND", "任务不存在")
        return task
    try:
        principal.require_resource_access(ResourceType.KNOWLEDGE_BASE, resource_id, "READ")
    except RolePermissionDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有查询任务的角色权限") from exc
    except ResourceScopeDenied as exc:
        raise AppError(404, "NOT_FOUND", "任务不存在或无访问权限") from exc
    return task


async def _task_data(task, request: Request) -> dict[str, Any]:
    cancellable = cancellation_target(task.status, task.stage) is not None
    retryable = can_retry(task.status, task.attempt_count, task.max_attempts)
    files: list[dict[str, Any]] = []
    if task.resource_type == "DOCUMENT":
        display_name = await _document_display_name(request, task.resource_id)
        if display_name:
            files.append(
                {
                    "file_name": display_name,
                    "document_id": str(task.resource_id),
                    "status": task.status.value,
                    "stage": task.stage.value,
                    "progress": task.progress,
                    "error_code": task.error_code,
                    "error_message": task.error_message,
                }
            )
    return {
        "task_id": str(task.id),
        "task_type": task.task_type,
        "resource_type": task.resource_type,
        "resource_id": str(task.resource_id),
        "status": task.status.value,
        "stage": task.stage.value,
        "progress": task.progress,
        "cancellable": cancellable,
        "retryable": retryable,
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "error_code": task.error_code,
        "error_message": task.error_message,
        "files": files,
        "result": task.result,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "started_at": None,
        "completed_at": task.updated_at.isoformat()
        if task.status in {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        else None,
    }


async def _document_display_name(request: Request, document_id: UUID) -> str | None:
    """Best-effort lookup of the document display name for task file info."""
    try:
        async with request.app.state.session_factory() as session:
            row = await session.scalar(
                select(Document.display_name).where(Document.id == document_id)
            )
            return row
    except Exception:
        return None


@router.get("/{task_id}")
async def get_task(request: Request, task_id: UUID, principal: CurrentPrincipal) -> dict[str, Any]:
    task = await _visible_task(request, principal, task_id)
    return success_response(request, await _task_data(task, request))


@router.post("/{task_id}/cancel")
async def cancel_task(
    request: Request, task_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    task = await _visible_task(request, principal, task_id)
    accepted = await request.app.state.task_repository.request_cancel(task_id)
    if not accepted:
        raise AppError(409, "TASK_NOT_CANCELLABLE", "任务已进入不可中断阶段或已经结束")
    refreshed = await request.app.state.task_repository.get(task_id)
    return success_response(request, await _task_data(refreshed or task, request))


@router.post("/{task_id}/retry")
async def retry_task(
    request: Request, task_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    task = await _visible_task(request, principal, task_id)
    event_types = {
        "INGEST": "knowledge.ingest",
        "REBUILD": "knowledge.rebuild",
        "DELETE": "knowledge.delete",
        "MERCHANT_ANALYSIS": "merchant.analysis",
        "LORA_TRAINING": "fine_tuning.train",
        "MODEL_EVALUATION": "fine_tuning.evaluate",
    }
    event_type = event_types.get(task.task_type)
    if event_type is None or not await request.app.state.task_repository.retry_with_outbox(
        task_id, event_type=event_type
    ):
        raise AppError(409, "TASK_NOT_RETRYABLE", "任务当前不可重试")
    refreshed = await request.app.state.task_repository.get(task_id)
    return success_response(request, await _task_data(refreshed or task, request))
