"""Endpoints completing the API specification's operational workflows."""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

import httpx
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import (
    ResourceScopeDenied,
    ResourceType,
    RolePermissionDenied,
    filter_authorized_resources,
)
from app.application.content_safety import ContentDirection
from app.application.knowledge import DocumentNotFound
from app.core.api import get_request_id, success_response
from app.core.config import get_settings
from app.core.errors import AppError
from app.infrastructure.db.repositories.operations import OperationsRepository

logger = logging.getLogger(__name__)

router = APIRouter(tags=["operations"])


class DataSourceCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    source_type: Literal["CSV", "FILE", "WEB", "API"] = "CSV"
    source_uri: str = Field(min_length=1, max_length=1000)
    source_sha256: str = Field(pattern=r"(?i)^[0-9a-f]{64}$")
    source_size_bytes: int = Field(gt=0)
    mime_type: str = Field(default="text/csv", max_length=128)
    parser_name: str | None = Field(default=None, max_length=64)
    parser_version: str = Field(default="1", min_length=1, max_length=64)
    cleaning_config: dict[str, object] = Field(default_factory=lambda: {"steps": []})
    splitter_config: dict[str, object] = Field(
        default_factory=lambda: {
            "strategy": "recursive",
            "chunk_size": 500,
            "chunk_overlap": 80,
        }
    )


class LoRAHyperparametersDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    r: int = Field(default=8, ge=1, le=64)
    lora_alpha: int = Field(default=16, ge=1)
    lora_dropout: float = Field(default=0.05, ge=0, lt=0.5)
    learning_rate: float = Field(default=2e-4, gt=0, le=1e-2)
    epochs: int = Field(default=3, ge=1, le=20)
    batch_size: int = Field(default=16, ge=1, le=128)
    seed: int = Field(default=42, ge=0)


class FineTuningCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    task_type: Literal[
        "sentiment_classification",
        "negative_reason_attribution",
    ]
    base_model_id: Literal["uer/roberta-base-finetuned-dianping-chinese"]
    dataset_id: UUID
    method: Literal["LORA", "QLORA"] = "LORA"
    hyperparameters: LoRAHyperparametersDTO = Field(default_factory=LoRAHyperparametersDTO)


class CloneKnowledgeBaseDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)


class AnalysisJobDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["FULL", "INCREMENTAL"] = "INCREMENTAL"
    since: datetime | None = None


class EvaluateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    benchmark: str = Field(default="fixed-test-v1", min_length=1, max_length=128)


class RegisterModelDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    provider: str = Field(default="local-lora", min_length=1, max_length=64)
    dimension: int | None = Field(default=None, gt=0)
    labels: list[str] | None = None


class ModerationDecisionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["APPROVE", "REJECT", "ESCALATE"]
    reason: str = Field(min_length=1, max_length=1000)


class UserReviewCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=10000)
    rating: float = Field(ge=0, le=5)


class ReviewModerateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["APPROVE", "REJECT"]
    reason: str = Field(default="", max_length=1000)


def _repository(request: Request) -> OperationsRepository:
    repository = getattr(request.app.state, "operations_repository", None)
    if repository is None:
        raise AppError(503, "SERVICE_UNAVAILABLE", "运营数据服务尚未配置")
    return repository


def _require_permission(principal: CurrentPrincipal, resource_type: str, action: str) -> None:
    try:
        principal.require_permission(resource_type, action)
    except RolePermissionDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc


def _require_resource(
    principal: CurrentPrincipal, resource_type: ResourceType, resource_id: UUID, action: str
) -> None:
    try:
        principal.require_resource_access(resource_type, resource_id, action)
    except RolePermissionDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc
    except ResourceScopeDenied as exc:
        raise AppError(404, "NOT_FOUND", "资源不存在或无访问权限") from exc


def _require_admin(principal: CurrentPrincipal) -> None:
    if not principal.is_platform_admin:
        raise AppError(403, "FORBIDDEN", "仅平台管理员可以执行此操作")


def _accepted(task_id: UUID, **extra: object) -> dict[str, object]:
    return {
        "task_id": str(task_id),
        "status": "PENDING",
        "progress": 0,
        "status_url": f"/api/v1/tasks/{task_id}",
        **extra,
    }


async def _analyze_approved_review(request: Request, review: object) -> None:
    """Best-effort sentiment analysis via model-gateway after review approval."""
    settings = get_settings()
    content = getattr(review, "content", "") or ""
    merchant_id = str(getattr(review, "merchant_id", ""))
    reviewed_at = getattr(review, "reviewed_at", None)
    if not content or not merchant_id:
        return
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                settings.model_gateway_sentiment_url,
                json={"reviews": [content]},
            )
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        if not results:
            return
        result = results[0]
        await _repository(request).create_review_analysis(
            merchant_id=merchant_id,
            review_text=content,
            sentiment=result.get("sentiment", "NEUTRAL"),
            confidence=float(result.get("confidence", 0.0)),
            model_version=data.get("model_version", "unknown"),
            aspect_labels=result.get("aspect_labels", []),
            negative_reasons=result.get("negative_reason", []),
            review_date=reviewed_at,
        )
        logger.info("Sentiment analysis completed for review %s", getattr(review, "id", ""))
    except Exception:
        logger.warning(
            "Sentiment analysis failed for review %s (non-blocking)",
            getattr(review, "id", ""),
            exc_info=True,
        )


@router.post("/knowledge-bases/{knowledge_base_id}/data-sources", status_code=201)
async def create_data_source(
    request: Request,
    knowledge_base_id: UUID,
    body: DataSourceCreateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_resource(principal, ResourceType.KNOWLEDGE_BASE, knowledge_base_id, "UPDATE")
    try:
        row = await _repository(request).create_data_source(
            knowledge_base_id=knowledge_base_id,
            name=body.name,
            source_type=body.source_type,
            config=body.model_dump(exclude={"name", "source_type"}),
            created_by=principal.user_id,
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在") from exc
    except IntegrityError as exc:
        raise AppError(409, "DATA_SOURCE_CONFLICT", "同名数据源已存在") from exc
    return success_response(request, _data_source(row), message="created")


@router.post("/data-sources/{data_source_id}/ingest", status_code=202)
async def ingest_data_source(
    request: Request, data_source_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    source = await _repository(request).get_data_source(data_source_id)
    if source is None:
        raise AppError(404, "NOT_FOUND", "数据源不存在")
    _require_resource(principal, ResourceType.KNOWLEDGE_BASE, source.knowledge_base_id, "UPDATE")
    try:
        source, document_id, task_id = await _repository(request).ingest_data_source(data_source_id)
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "数据源不存在") from exc
    except ValueError as exc:
        raise AppError(422, "INVALID_DATA_SOURCE", str(exc)) from exc
    return success_response(
        request,
        _accepted(
            task_id,
            data_source_id=str(source.id),
            document_id=str(document_id),
        ),
        message="accepted",
    )


@router.post("/knowledge-bases/{knowledge_base_id}/clone", status_code=202)
async def clone_knowledge_base(
    request: Request,
    knowledge_base_id: UUID,
    body: CloneKnowledgeBaseDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_resource(principal, ResourceType.KNOWLEDGE_BASE, knowledge_base_id, "READ")
    _require_permission(principal, "KNOWLEDGE_BASE", "CREATE")
    try:
        clone, task_ids = await _repository(request).clone_knowledge_base(
            knowledge_base_id, name=body.name, owner_id=principal.user_id
        )
        await request.app.state.authorization_repository.grant_user_resource(
            user_id=principal.user_id,
            resource_type=ResourceType.KNOWLEDGE_BASE,
            resource_id=clone.id,
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在") from exc
    except IntegrityError as exc:
        raise AppError(409, "KNOWLEDGE_BASE_CONFLICT", "目标知识库名称已存在") from exc
    return success_response(
        request,
        {
            "knowledge_base_id": str(clone.id),
            "source_knowledge_base_id": str(knowledge_base_id),
            "status": "PENDING" if task_ids else "SUCCEEDED",
            "task_ids": [str(value) for value in task_ids],
        },
        message="accepted",
    )


@router.get("/documents/{document_id}/preview")
async def preview_document(
    request: Request,
    document_id: UUID,
    principal: CurrentPrincipal,
    query: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    try:
        knowledge_base_id = await request.app.state.knowledge_repository.scoped(
            principal
        ).get_document_knowledge_base_id(document_id, action="READ")
    except DocumentNotFound as exc:
        raise AppError(404, "NOT_FOUND", "文档不存在") from exc
    _require_resource(principal, ResourceType.KNOWLEDGE_BASE, knowledge_base_id, "READ")
    result = await _repository(request).preview_document(document_id, query=query, limit=limit)
    if result is None:
        raise AppError(404, "NOT_FOUND", "文档不存在")
    return success_response(request, result)


@router.get("/merchants/directory")
async def merchants_directory(
    request: Request,
    principal: CurrentPrincipal,
    keyword: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Public merchant directory for all authenticated users (no resource scoping)."""
    rows = await _repository(request).search_merchants_directory(keyword=keyword, limit=limit)
    return success_response(
        request,
        {
            "items": [
                {
                    "id": str(row.id),
                    "name": row.name,
                    "category": row.category,
                    "address": row.address,
                }
                for row in rows
            ],
        },
    )


@router.get("/merchants")
async def list_merchants(
    request: Request,
    principal: CurrentPrincipal,
    category: str | None = None,
    min_price_cent: Annotated[int | None, Query(ge=0)] = None,
    max_price_cent: Annotated[int | None, Query(ge=0)] = None,
    business_status: Literal["OPEN", "CLOSED", "SUSPENDED", "UNKNOWN"] | None = None,
    longitude: Annotated[float | None, Query(ge=-180, le=180)] = None,
    latitude: Annotated[float | None, Query(ge=-90, le=90)] = None,
    radius_m: Annotated[int | None, Query(gt=0, le=100_000)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    _require_permission(principal, "MERCHANT", "READ")
    if min_price_cent is not None and max_price_cent is not None:
        if min_price_cent > max_price_cent:
            raise AppError(422, "INVALID_PRICE_RANGE", "最低价格不能大于最高价格")
    if any(value is not None for value in (longitude, latitude, radius_m)) and any(
        value is None for value in (longitude, latitude, radius_m)
    ):
        raise AppError(422, "INVALID_GEO_FILTER", "经度、纬度和半径必须同时提供")
    rows, total = await _repository(request).list_merchants(
        category=category,
        min_price=min_price_cent,
        max_price=max_price_cent,
        business_status=business_status,
        longitude=longitude,
        latitude=latitude,
        radius_m=radius_m,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    rows = filter_authorized_resources(
        principal,
        rows,
        resource_type=ResourceType.MERCHANT,
        action="READ",
        id_getter=lambda row: row.id,
    )
    return success_response(
        request,
        {
            "items": [_merchant_data(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total if principal.is_platform_admin else len(rows),
        },
    )


@router.get("/merchants/{merchant_id}")
async def get_merchant(
    request: Request, merchant_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_permission(principal, "MERCHANT", "READ")
    result = await _repository(request).get_merchant(merchant_id)
    if result is None:
        raise AppError(404, "NOT_FOUND", "商家不存在")
    row, summary = result
    return success_response(request, {**_merchant_data(row), "reputation_summary": summary})


@router.get("/merchants/{merchant_id}/reviews")
async def list_merchant_reviews(
    request: Request,
    merchant_id: UUID,
    principal: CurrentPrincipal,
    sentiment: Literal["POSITIVE", "NEUTRAL", "NEGATIVE"] | None = None,
    tag: str | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    _require_permission(principal, "MERCHANT", "READ")
    if start_at and end_at and start_at >= end_at:
        raise AppError(422, "INVALID_TIME_RANGE", "开始时间必须早于结束时间")
    rows, total = await _repository(request).list_reviews(
        merchant_id,
        sentiment=sentiment,
        tag=tag,
        start_at=start_at,
        end_at=end_at,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success_response(
        request,
        {
            "items": [_json_data(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/merchants/{merchant_id}/reviews", status_code=201)
async def submit_user_review(
    request: Request,
    merchant_id: UUID,
    body: UserReviewCreateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    # Any authenticated user can submit a review (no resource grant required)
    # Sensitive word check
    safety_service = getattr(request.app.state, "content_safety_service", None)
    if safety_service is not None:
        check_result = await safety_service.check(
            content=body.content,
            direction=ContentDirection.INPUT,
            actor_id=principal.user_id,
            request_id=get_request_id(request),
        )
        if not check_result.allowed:
            raise AppError(422, "SENSITIVE_CONTENT_REJECTED", "评论包含受限内容，已拒绝提交")
    try:
        review = await _repository(request).create_user_review(
            merchant_id=merchant_id,
            user_id=principal.user_id,
            content=body.content,
            rating=body.rating,
            author_name=principal.display_name,
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "商家不存在") from exc
    return success_response(
        request,
        {
            "id": str(review.id),
            "merchant_id": str(review.merchant_id),
            "status": review.status,
            "rating": float(review.rating) if review.rating is not None else None,
            "created_at": review.created_at.isoformat(),
        },
        message="评论已提交，等待审核",
    )


@router.get("/users/me/reviews")
async def list_my_reviews(
    request: Request,
    principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    rows, total = await _repository(request).list_user_reviews(
        principal.user_id, limit=page_size, offset=(page - 1) * page_size
    )
    return success_response(
        request,
        {
            "items": [
                {
                    "id": str(row.id),
                    "merchant_id": str(row.merchant_id),
                    "content": row.content,
                    "rating": float(row.rating) if row.rating is not None else None,
                    "status": row.status,
                    "created_at": row.created_at.isoformat(),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/reviews/pending")
async def list_pending_reviews(
    request: Request,
    principal: CurrentPrincipal,
    status: Literal["PENDING", "PUBLISHED", "REJECTED"] = "PENDING",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """Admin: list reviews by status for moderation."""
    _require_admin(principal)
    rows, total = await _repository(request).list_pending_reviews(
        status=status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return success_response(
        request,
        {
            "items": [
                {
                    "id": str(row.id),
                    "merchant_id": str(row.merchant_id),
                    "author": row.author_ref,
                    "content": row.content,
                    "rating": float(row.rating) if row.rating is not None else None,
                    "status": row.status,
                    "source_type": row.source_type,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/reviews/{review_id}/moderate")
async def moderate_user_review(
    request: Request,
    review_id: UUID,
    body: ReviewModerateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_admin(principal)
    reason = body.reason
    if not reason:
        reason = "审核通过" if body.decision == "APPROVE" else "不符合社区规范"
    try:
        review = await _repository(request).moderate_user_review(
            review_id,
            decision=body.decision,
            reason=reason,
            moderator_id=principal.user_id,
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "评论不存在") from exc
    except ValueError as exc:
        raise AppError(422, "INVALID_STATUS_TRANSITION", str(exc)) from exc
    # Trigger sentiment analysis on approval (best-effort)
    if review.status == "PUBLISHED":
        await _analyze_approved_review(request, review)
    return success_response(
        request,
        {
            "id": str(review.id),
            "status": review.status,
            "moderated_by": str(principal.user_id),
        },
        message="审核完成",
    )


@router.post("/merchants/{merchant_id}/analysis-jobs", status_code=202)
async def create_merchant_analysis_job(
    request: Request,
    merchant_id: UUID,
    body: AnalysisJobDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_resource(principal, ResourceType.MERCHANT, merchant_id, "UPDATE")
    try:
        task_id = await _repository(request).create_analysis_job(
            merchant_id, mode=body.mode, since=body.since
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "商家不存在") from exc
    return success_response(request, _accepted(task_id), message="accepted")


@router.get("/merchants/{merchant_id}/sentiment")
async def merchant_sentiment(
    request: Request,
    merchant_id: UUID,
    principal: CurrentPrincipal,
    granularity: Literal["day", "week", "month"] = "week",
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    _require_permission(principal, "MERCHANT", "READ")
    service = request.app.state.analytics_service
    trend = await service.get_sentiment_trend(
        str(merchant_id), granularity=granularity, start_date=start_at, end_date=end_at
    )
    summary = (await service.compare_merchants([str(merchant_id), str(UUID(int=0))]))["merchants"][
        0
    ]
    evidence = await service.drill_down_reviews(
        str(merchant_id), start_date=start_at, end_date=end_at, limit=20
    )
    model_version = evidence[0].model_version if evidence else "unknown"
    return success_response(
        request,
        {
            "merchant_id": str(merchant_id),
            "distribution": {
                "positive_rate": summary["positive_rate"],
                "sample_count": summary["sample_count"],
            },
            "trend": trend,
            "model_version": model_version,
            "prompt_version": "analytics-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "evidence_review_ids": [str(row.id) for row in evidence],
        },
    )


@router.get("/merchants/{merchant_id}/topics")
async def merchant_topics(
    request: Request,
    merchant_id: UUID,
    principal: CurrentPrincipal,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    _require_permission(principal, "MERCHANT", "READ")
    service = request.app.state.analytics_service
    evidence = await service.drill_down_reviews(
        str(merchant_id), start_date=start_at, end_date=end_at, limit=20
    )
    model_version = evidence[0].model_version if evidence else "unknown"
    return success_response(
        request,
        {
            "merchant_id": str(merchant_id),
            "topics": await service.get_merchant_highlights(
                str(merchant_id),
                min_mentions=1,
                start_date=start_at,
                end_date=end_at,
            ),
            "negative_reasons": await service.get_negative_reason_aggregation(
                str(merchant_id), start_date=start_at, end_date=end_at
            ),
            "model_version": model_version,
            "prompt_version": "analytics-v1",
            "generated_at": datetime.now(UTC).isoformat(),
            "evidence_review_ids": [str(row.id) for row in evidence],
        },
    )


@router.post("/fine-tuning/jobs", status_code=202)
async def create_fine_tuning_job(
    request: Request, body: FineTuningCreateDTO, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_admin(principal)
    dataset_id = body.dataset_id
    try:
        row = await _repository(request).create_fine_tuning_job(
            dataset_id=dataset_id,
            task_type=body.task_type,
            base_model_ref=body.base_model_id,
            method=body.method,
            hyperparameters=body.hyperparameters.model_dump(),
            created_by=principal.user_id,
        )
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "数据集不存在") from exc
    except ValueError as exc:
        raise AppError(409, "DATASET_NOT_TRAINABLE", str(exc)) from exc
    except IntegrityError as exc:
        raise AppError(409, "FINE_TUNING_JOB_EXISTS", "相同训练配置的任务已存在") from exc
    return success_response(
        request,
        _accepted(row.async_task_id, job_id=str(row.id)),
        message="accepted",
    )


@router.get("/fine-tuning/jobs/{job_id}")
async def get_fine_tuning_job(
    request: Request, job_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_admin(principal)
    row = await _repository(request).get_fine_tuning_job(job_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "训练任务不存在")
    return success_response(request, _fine_tuning_data(row))


@router.post("/fine-tuning/jobs/{job_id}/cancel")
async def cancel_fine_tuning_job(
    request: Request, job_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        row = await _repository(request).cancel_fine_tuning_job(job_id)
    except ValueError as exc:
        raise AppError(409, "JOB_NOT_CANCELLABLE", str(exc)) from exc
    if row is None:
        raise AppError(404, "NOT_FOUND", "训练任务不存在")
    return success_response(request, _fine_tuning_data(row))


@router.post("/fine-tuning/jobs/{job_id}/evaluate", status_code=202)
async def evaluate_fine_tuning_job(
    request: Request,
    job_id: UUID,
    body: EvaluateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_admin(principal)
    try:
        task_id = await _repository(request).evaluate_fine_tuning_job(job_id, body.benchmark)
    except LookupError as exc:
        raise AppError(404, "NOT_FOUND", "训练任务不存在") from exc
    except ValueError as exc:
        raise AppError(409, "JOB_NOT_EVALUATABLE", str(exc)) from exc
    return success_response(request, _accepted(task_id, job_id=str(job_id)), message="accepted")


@router.post("/fine-tuning/jobs/{job_id}/register-model", status_code=201)
async def register_fine_tuned_model(
    request: Request,
    job_id: UUID,
    body: RegisterModelDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_admin(principal)
    job = await _repository(request).get_fine_tuning_job(job_id)
    if job is None:
        raise AppError(404, "NOT_FOUND", "训练任务不存在")
    evaluation = job.evaluation_json or {}
    if job.status != "SUCCEEDED" or evaluation.get("passed") is not True:
        raise AppError(409, "EVALUATION_GATE_FAILED", "训练产物尚未通过评测门禁")
    if not job.artifact_uri or not job.artifact_sha256:
        raise AppError(409, "ARTIFACT_MISSING", "训练产物信息不完整")
    governance = request.app.state.governance_repository
    try:
        model = await governance.register_model(
            code=body.code,
            name=body.name,
            task_type=job.task_type,
            provider=body.provider,
            version=body.version,
            base_model_ref=job.base_model_ref,
            adapter_uri=job.artifact_uri,
            artifact_sha256=job.artifact_sha256,
            dimension=body.dimension,
            labels=body.labels,
            metrics=job.metrics_json,
            created_by=principal.user_id,
            request_id=get_request_id(request),
        )
    except (ValueError, IntegrityError) as exc:
        raise AppError(409, "MODEL_REGISTRATION_CONFLICT", str(exc)) from exc
    return success_response(
        request,
        {"model_version_id": str(model.id), "fine_tuning_job_id": str(job.id)},
        message="registered",
    )


@router.get("/moderation/cases")
async def list_moderation_cases(
    request: Request,
    principal: CurrentPrincipal,
    status: Literal["PENDING_REVIEW", "APPROVED", "REJECTED"] | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    _require_admin(principal)
    rows, total = await _repository(request).list_moderation_cases(
        status=status, limit=page_size, offset=(page - 1) * page_size
    )
    return success_response(
        request,
        {
            "items": [
                {
                    "id": str(row.id),
                    "content_type": "FEEDBACK",
                    "content_id": str(row.message_id),
                    "status": row.review_status,
                    "reason_codes": row.reason_codes_json or [],
                    "pii_flagged": bool(row.pii_flagged),
                    "created_at": row.created_at.isoformat(),
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/moderation/cases/{case_id}/decision")
async def decide_moderation_case(
    request: Request,
    case_id: UUID,
    body: ModerationDecisionDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _require_admin(principal)
    row = await _repository(request).decide_moderation_case(case_id, body.decision)
    if row is None:
        raise AppError(404, "NOT_FOUND", "审核工单不存在")
    return success_response(
        request,
        {
            "id": str(row.id),
            "decision": body.decision,
            "status": row.review_status,
            "reason": body.reason,
            "decided_by": str(principal.user_id),
        },
        message="decided",
    )


@router.get("/analytics/overview")
async def analytics_overview(
    request: Request,
    principal: CurrentPrincipal,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, Any]:
    _require_admin(principal)
    if start_at and end_at and start_at >= end_at:
        raise AppError(422, "INVALID_TIME_RANGE", "开始时间必须早于结束时间")
    data = await _repository(request).analytics_overview(start_at, end_at)
    return success_response(
        request,
        {
            **data,
            "period_start": start_at.isoformat() if start_at else None,
            "period_end": end_at.isoformat() if end_at else None,
            "generated_at": datetime.now().astimezone().isoformat(),
        },
    )


def _data_source(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "knowledge_base_id": str(row.knowledge_base_id),
        "name": row.name,
        "source_type": row.source_type,
        "config": row.config_json,
        "status": row.status,
        "version": row.version,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


def _merchant_data(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "category": row.category,
        "region_id": str(row.region_id) if row.region_id else None,
        "address": row.address,
        "longitude": float(row.longitude),
        "latitude": float(row.latitude),
        "avg_price_cent": row.avg_price_cent,
        "rating": float(row.rating),
        "business_hours": row.business_hours_json,
        "business_status": row.business_status,
        "last_verified_at": (row.last_verified_at.isoformat() if row.last_verified_at else None),
        "data_updated_at": row.updated_at.isoformat(),
    }


def _fine_tuning_data(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "task_id": str(row.async_task_id),
        "dataset_id": str(row.dataset_id),
        "task_type": row.task_type,
        "base_model_id": row.base_model_ref,
        "method": row.method,
        "hyperparameters": row.hyperparameters_json,
        "status": row.status,
        "metrics": row.metrics_json,
        "evaluation": row.evaluation_json,
        "log_uri": row.log_uri,
        "artifact_uri": row.artifact_uri,
        "artifact_sha256": row.artifact_sha256,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


def _json_data(value: dict[str, object]) -> dict[str, object]:
    return {
        key: item.isoformat() if isinstance(item, datetime) else item for key, item in value.items()
    }
