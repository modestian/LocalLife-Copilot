"""Dataset REST endpoints.

Implements the endpoints defined in:
- docs/project/大众点评AI智能助手-03-API接口规范.md §8.2:
  POST /api/v1/fine-tuning/datasets — generate immutable JSONL dataset
  GET  /api/v1/fine-tuning/datasets/{id} — return metadata and reports

Authorization per §8.2 and domain/feedback.py:
- DATASET_CREATE_PERMISSION required for generation
- DATASET_READ_PERMISSION required for retrieval
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request

from app.api.dependencies.authorization import CurrentPrincipal, require_permission
from app.application.dataset_service import (
    DatasetNotFoundError,
    DatasetService,
    EmptyDatasetError,
)
from app.core.api import success_response
from app.core.errors import AppError
from app.domain.feedback import (
    DATASET_CREATE_PERMISSION,
    DATASET_READ_PERMISSION,
    DatasetCreateRequest,
    DatasetResponse,
    DatasetStatistics,
)

router = APIRouter(prefix="/fine-tuning", tags=["datasets"])


# ---------------------------------------------------------------------------
# Dependency injection
# ---------------------------------------------------------------------------


def get_dataset_service(request: Request) -> DatasetService:
    service: DatasetService | None = getattr(request.app.state, "dataset_service", None)
    if service is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "数据集服务尚未配置")
    return service


DatasetServiceDependency = Annotated[DatasetService, Depends(get_dataset_service)]

DatasetCreatePrincipal = Annotated[
    CurrentPrincipal, Depends(require_permission("dataset", DATASET_CREATE_PERMISSION))
]
DatasetReadPrincipal = Annotated[
    CurrentPrincipal, Depends(require_permission("dataset", DATASET_READ_PERMISSION))
]


# ---------------------------------------------------------------------------
# POST /api/v1/fine-tuning/datasets
# ---------------------------------------------------------------------------


@router.post("/datasets")
async def create_dataset(
    request: Request,
    payload: DatasetCreateRequest,
    principal: DatasetCreatePrincipal,
    service: DatasetServiceDependency,
) -> dict[str, Any]:
    """Generate an immutable JSONL dataset from filtered feedback.

    Per §8.2: generates a content-addressed JSONL dataset with SHA-256 hash,
    stratified split and quality report.  The dataset is immutable once READY.

    Authorization: requires DATASET_CREATE_PERMISSION (admin/model-manager).
    """
    try:
        record = await service.generate_dataset(
            name=payload.name,
            task_type=payload.task_type,
            filter_config=payload.filter,
            split_config=payload.split_config,
        )
    except EmptyDatasetError as exc:
        raise AppError(422, "DATASET_EMPTY", str(exc)) from exc

    response = _build_dataset_response(record)
    return success_response(request, response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# GET /api/v1/fine-tuning/datasets/{id}
# ---------------------------------------------------------------------------


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    request: Request,
    dataset_id: Annotated[UUID, Path()],
    principal: DatasetReadPrincipal,
    service: DatasetServiceDependency,
) -> dict[str, Any]:
    """Retrieve dataset metadata, hash and quality report.

    Per §8.2: returns data count, hash, redaction and quality report.
    """
    try:
        record = await service.get_dataset(dataset_id)
    except DatasetNotFoundError as exc:
        raise AppError(404, "DATASET_NOT_FOUND", str(exc)) from exc

    response = _build_dataset_response(record)
    return success_response(request, response.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_dataset_response(record: Any) -> DatasetResponse:
    """Convert a DatasetRecord to a DatasetResponse DTO."""
    stats = record.statistics_json
    statistics = DatasetStatistics(
        total_samples=stats.get("total_samples", record.sample_count),
        train_samples=stats.get("train_samples", 0),
        validation_samples=stats.get("validation_samples", 0),
        test_samples=stats.get("test_samples", 0),
        label_distribution=stats.get("label_distribution", {}),
        source_distribution=stats.get("source_distribution", {}),
    )
    return DatasetResponse(
        id=record.id,
        name=record.name,
        task_type=record.task_type,
        dataset_hash=record.dataset_hash,
        storage_uri=record.storage_uri,
        sample_count=record.sample_count,
        status=record.status,
        redaction_version=record.redaction_version,
        statistics=statistics,
        quality_report_uri=record.quality_report_uri,
        quality_report_hash=record.quality_report_hash,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
