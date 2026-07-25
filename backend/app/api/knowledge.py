import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select

from app.api.dependencies.authorization import CurrentPrincipal
from app.application.authorization import (
    AuthorizationPrincipal,
    ResourceScopeDenied,
    ResourceType,
    RolePermissionDenied,
    filter_authorized_resources,
)
from app.application.knowledge import (
    DocumentInput,
    DocumentNotFound,
    DocumentPatch,
    DocumentVersionInput,
    InvalidRollbackTarget,
    KnowledgeBaseInput,
    KnowledgeBaseNotFound,
    KnowledgeBasePatch,
    KnowledgeService,
)
from app.application.upload_security import UnsafeUploadError, validate_upload
from app.core.api import success_response
from app.core.errors import AppError
from app.core.ids import uuid7
from app.infrastructure.db.models.governance import ModelDefinition, ModelVersion
from app.infrastructure.db.models.identity import Department, User
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion

router = APIRouter(tags=["knowledge"])


class KnowledgeBaseCreateDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    department_id: UUID | None = None
    owner_id: UUID | None = None
    embedding_model_id: UUID
    chunk_size: int = Field(default=500, ge=100, le=4000)
    chunk_overlap: int = Field(default=80, ge=0)


class KnowledgeBasePatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    owner_id: UUID | None = None
    embedding_model_id: UUID | None = None
    chunk_size: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None


class DocumentPatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    mime_type: str | None = Field(default=None, max_length=128)
    status: Literal["UPLOADED", "READY", "FAILED", "ARCHIVED"] | None = None


class RollbackDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_version_no: int = Field(ge=1)


def _knowledge_repository(request: Request, principal: AuthorizationPrincipal | None = None):
    repository = request.app.state.knowledge_repository
    return repository.scoped(principal) if principal is not None else repository


def _knowledge_service(request: Request, principal: AuthorizationPrincipal) -> KnowledgeService:
    return KnowledgeService(_knowledge_repository(request, principal))


def _task_repository(request: Request):
    return request.app.state.task_repository


def _authorize_permission(
    principal: AuthorizationPrincipal, resource_type: str, action: str
) -> None:
    try:
        principal.require_permission(resource_type, action)
    except RolePermissionDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc


def _authorize_knowledge_base(
    principal: AuthorizationPrincipal, knowledge_base_id: UUID, action: str
) -> None:
    try:
        principal.require_resource_access(ResourceType.KNOWLEDGE_BASE, knowledge_base_id, action)
    except RolePermissionDenied as exc:
        raise AppError(403, "FORBIDDEN", "没有执行此操作的角色权限") from exc
    except ResourceScopeDenied as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在或无访问权限") from exc


async def _authorize_document(
    request: Request,
    principal: AuthorizationPrincipal,
    document_id: UUID,
    action: str,
) -> UUID:
    try:
        knowledge_base_id = await _knowledge_repository(
            request, principal
        ).get_document_knowledge_base_id(
            document_id,
            action=action,
        )
    except DocumentNotFound as exc:
        raise AppError(404, "NOT_FOUND", "文档不存在") from exc
    _authorize_knowledge_base(principal, knowledge_base_id, action)
    return knowledge_base_id


def _serialize(value: object) -> dict[str, Any]:
    result = asdict(value)  # type: ignore[arg-type]
    for key, item in result.items():
        if isinstance(item, UUID):
            result[key] = str(item)
    return result


async def _enrich_knowledge_base_data(request: Request, items: list[dict[str, Any]]) -> None:
    """Enrich serialized knowledge base dicts with related names and statistics."""
    if not items:
        return
    session_factory = request.app.state.session_factory
    owner_ids = {UUID(item["owner_id"]) for item in items if item.get("owner_id")}
    department_ids = {UUID(item["department_id"]) for item in items if item.get("department_id")}
    kb_ids = {UUID(item["id"]) for item in items}

    async with session_factory() as session:
        # Resolve user display names
        user_names: dict[UUID, str] = {}
        if owner_ids:
            rows = await session.scalars(select(User).where(User.id.in_(owner_ids)))
            user_names = {u.id: u.display_name for u in rows.all()}

        # Resolve department names
        dept_names: dict[UUID, str] = {}
        if department_ids:
            rows = await session.scalars(
                select(Department).where(Department.id.in_(department_ids))
            )
            dept_names = {d.id: d.name for d in rows.all()}

        # Resolve embedding model names
        embedding_model_ids = {
            UUID(item["embedding_model_version_id"])
            for item in items
            if item.get("embedding_model_version_id")
        }
        model_names: dict[UUID, str] = {}
        if embedding_model_ids:
            model_rows = await session.execute(
                select(ModelVersion.id, ModelDefinition.name)
                .join(
                    ModelDefinition,
                    ModelVersion.model_definition_id == ModelDefinition.id,
                )
                .where(ModelVersion.id.in_(embedding_model_ids))
            )
            model_names = {r[0]: r[1] for r in model_rows.all()}

        # Compute document statistics per knowledge base
        stats_query = (
            select(
                Document.knowledge_base_id,
                func.count().label("document_count"),
                func.sum(case((Document.status == "READY", 1), else_=0)).label(
                    "ready_document_count"
                ),
                func.sum(case((Document.status == "FAILED", 1), else_=0)).label(
                    "failed_document_count"
                ),
                func.max(Document.updated_at).label("latest_indexed_at"),
            )
            .where(
                Document.knowledge_base_id.in_(kb_ids),
                Document.deleted_at.is_(None),
                Document.status != "DELETED",
            )
            .group_by(Document.knowledge_base_id)
        )
        stats_rows = (await session.execute(stats_query)).all()
        chunk_count_query = (
            select(
                Document.knowledge_base_id,
                func.coalesce(func.count(Chunk.id), 0).label("chunk_count"),
            )
            .select_from(Document)
            .outerjoin(
                DocumentVersion,
                (DocumentVersion.document_id == Document.id) & DocumentVersion.is_current.is_(True),
            )
            .outerjoin(
                Chunk,
                (Chunk.document_version_id == DocumentVersion.id)
                & (Chunk.index_status != "DELETED"),
            )
            .where(
                Document.knowledge_base_id.in_(kb_ids),
                Document.deleted_at.is_(None),
                Document.status != "DELETED",
            )
            .group_by(Document.knowledge_base_id)
        )
        chunk_rows = (await session.execute(chunk_count_query)).all()
        chunk_counts = {r[0]: r[1] for r in chunk_rows}

    for item in items:
        kb_id = UUID(item["id"])
        owner_id = UUID(item["owner_id"]) if item.get("owner_id") else None
        dept_id = UUID(item["department_id"]) if item.get("department_id") else None

        item["owner_name"] = user_names.get(owner_id, "") if owner_id else ""
        item["department_name"] = dept_names.get(dept_id) if dept_id else None
        embedding_model_version_id = (
            UUID(item["embedding_model_version_id"])
            if item.get("embedding_model_version_id")
            else None
        )
        item["embedding_model_id"] = (
            str(embedding_model_version_id) if embedding_model_version_id else ""
        )
        item["embedding_model_name"] = model_names.get(embedding_model_version_id, "")

        stat = next((r for r in stats_rows if r[0] == kb_id), None)
        if stat:
            item["statistics"] = {
                "document_count": stat[1] or 0,
                "chunk_count": int(chunk_counts.get(kb_id, 0) or 0),
                "ready_document_count": int(stat[2] or 0),
                "failed_document_count": int(stat[3] or 0),
            }
            item["latest_indexed_at"] = stat[4].isoformat() if stat[4] else None
        else:
            item["statistics"] = {
                "document_count": 0,
                "chunk_count": 0,
                "ready_document_count": 0,
                "failed_document_count": 0,
            }
            item["latest_indexed_at"] = None


def _accepted(task_id: UUID) -> dict[str, object]:
    return {
        "task_id": str(task_id),
        "status": "PENDING",
        "progress": 0,
        "status_url": f"/api/v1/tasks/{task_id}",
    }


@router.post("/knowledge-bases")
async def create_knowledge_base(
    request: Request,
    body: KnowledgeBaseCreateDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _authorize_permission(principal, "KNOWLEDGE_BASE", "CREATE")
    if not principal.is_platform_admin and body.department_id not in {
        None,
        principal.department_id,
    }:
        raise AppError(403, "FORBIDDEN", "不能在其他租户下创建知识库")
    if not principal.is_platform_admin and body.owner_id not in {None, principal.user_id}:
        raise AppError(403, "FORBIDDEN", "不能为其他用户创建知识库")
    tenant_id = body.department_id if principal.is_platform_admin else principal.department_id
    if tenant_id is None:
        raise AppError(422, "TENANT_REQUIRED", "创建知识库需要部门或租户上下文")
    try:
        created = await _knowledge_service(request, principal).create_knowledge_base(
            KnowledgeBaseInput(
                owner_id=(body.owner_id or principal.user_id),
                name=body.name,
                embedding_model_version_id=body.embedding_model_id,
                tenant_id=tenant_id,
                department_id=body.department_id,
                description=body.description,
                chunk_size=body.chunk_size,
                chunk_overlap=body.chunk_overlap,
            )
        )
        await request.app.state.authorization_repository.grant_user_resource(
            user_id=principal.user_id,
            resource_type=ResourceType.KNOWLEDGE_BASE,
            resource_id=created.id,
        )
    except ValueError as exc:
        raise AppError(400, "INVALID_KNOWLEDGE_BASE", str(exc)) from exc
    data = _serialize(created)
    await _enrich_knowledge_base_data(request, [data])
    return success_response(request, data)


@router.get("/knowledge-bases")
async def list_knowledge_bases(
    request: Request,
    principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    tenant_id: Annotated[UUID | None, Query()] = None,
    department_id: Annotated[UUID | None, Query()] = None,
    name: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    status: Annotated[Literal["ACTIVE", "ARCHIVED", "DELETED"] | None, Query()] = None,
) -> dict[str, Any]:
    _authorize_permission(principal, "KNOWLEDGE_BASE", "READ")
    if principal.department_id is None and not principal.is_platform_admin:
        raise AppError(403, "TENANT_CONTEXT_REQUIRED", "当前账号缺少租户上下文")
    effective_tenant_id = (
        tenant_id or principal.department_id
        if principal.is_platform_admin
        else principal.department_id
    )
    if effective_tenant_id is None:
        raise AppError(422, "TENANT_REQUIRED", "平台管理员查询时需要部门上下文")
    rows = await _knowledge_service(request, principal).list_knowledge_bases(
        effective_tenant_id,
        name=name,
        status=status,
        department_id=department_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    rows = filter_authorized_resources(
        principal,
        rows,
        resource_type=ResourceType.KNOWLEDGE_BASE,
        action="READ",
        id_getter=lambda row: row.id,
    )
    total = await _knowledge_service(request, principal).count_knowledge_bases(
        effective_tenant_id,
        name=name,
        status=status,
        department_id=department_id,
    )
    items = [_serialize(row) for row in rows]
    await _enrich_knowledge_base_data(request, items)
    return success_response(
        request,
        {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.get("/knowledge-bases/{knowledge_base_id}")
async def get_knowledge_base(
    request: Request, knowledge_base_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "READ")
    try:
        row = await _knowledge_service(request, principal).get_knowledge_base(knowledge_base_id)
    except KnowledgeBaseNotFound as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在") from exc
    data = _serialize(row)
    await _enrich_knowledge_base_data(request, [data])
    return success_response(request, data)


@router.patch("/knowledge-bases/{knowledge_base_id}")
async def update_knowledge_base(
    request: Request,
    knowledge_base_id: UUID,
    body: KnowledgeBasePatchDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "UPDATE")
    try:
        row = await _knowledge_service(request, principal).update_knowledge_base(
            knowledge_base_id, KnowledgeBasePatch(**body.model_dump())
        )
    except (KnowledgeBaseNotFound, ValueError) as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在或更新无效") from exc
    data = _serialize(row)
    await _enrich_knowledge_base_data(request, [data])
    return success_response(request, data)


@router.delete("/knowledge-bases/{knowledge_base_id}", status_code=202)
async def delete_knowledge_base(
    request: Request, knowledge_base_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "DELETE")
    task_ids = await _task_repository(request).delete_knowledge_base_with_outbox(knowledge_base_id)
    if task_ids is None:
        raise AppError(404, "NOT_FOUND", "知识库不存在")
    return success_response(
        request,
        {
            "id": str(knowledge_base_id),
            "status": "DELETED",
            "task_ids": [str(task_id) for task_id in task_ids],
        },
        message="accepted",
    )


@router.get("/knowledge-bases/{knowledge_base_id}/documents")
async def list_documents(
    request: Request,
    knowledge_base_id: UUID,
    principal: CurrentPrincipal,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    status: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "READ")
    try:
        rows = await _knowledge_service(request, principal).list_documents(
            knowledge_base_id, status=status, limit=page_size, offset=(page - 1) * page_size
        )
        total = await _knowledge_service(request, principal).count_documents(
            knowledge_base_id, status=status
        )
    except KnowledgeBaseNotFound as exc:
        raise AppError(404, "NOT_FOUND", "知识库不存在") from exc
    return success_response(
        request,
        {
            "items": [_serialize(row) for row in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )


@router.post("/knowledge-bases/{knowledge_base_id}/reindex", status_code=202)
async def reindex_knowledge_base(
    request: Request, knowledge_base_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "UPDATE")
    rows = await _knowledge_service(request, principal).list_documents(knowledge_base_id, limit=200)
    if not rows:
        raise AppError(409, "NO_DOCUMENTS", "知识库没有可重建索引的文档")
    task_ids = [await _create_document_task(request, document.id, "REBUILD") for document in rows]
    data = _accepted(task_ids[0])
    data["task_ids"] = [str(value) for value in task_ids]
    return success_response(request, data, message="accepted")


@router.post("/knowledge-bases/{knowledge_base_id}/documents:upload", status_code=202)
async def upload_documents(
    request: Request,
    knowledge_base_id: UUID,
    principal: CurrentPrincipal,
    files: Annotated[list[UploadFile], File(alias="files[]")],
    splitter: Annotated[Literal["recursive", "semantic"], Form()] = "recursive",
    chunk_size: Annotated[int, Form(ge=100, le=4000)] = 500,
    chunk_overlap: Annotated[int, Form(ge=0)] = 80,
    force_new_version: Annotated[bool, Form()] = False,
    import_mode: Annotated[Literal["knowledge", "merchant_reviews"], Form()] = "knowledge",
) -> dict[str, Any]:
    _authorize_knowledge_base(principal, knowledge_base_id, "UPDATE")
    if import_mode == "merchant_reviews":
        _authorize_permission(principal, "MERCHANT", "CREATE")
    if not files or len(files) > 20:
        raise AppError(400, "INVALID_UPLOAD", "每次必须上传 1 至 20 个文件")
    if chunk_overlap >= chunk_size:
        raise AppError(400, "INVALID_CHUNKING", "chunk_overlap 必须小于 chunk_size")

    task_ids: list[UUID] = []
    file_results: list[dict[str, str]] = []
    for upload in files:
        content = await upload.read(request.app.state.settings.max_ingestion_source_bytes + 1)
        if not content or len(content) > request.app.state.settings.max_ingestion_source_bytes:
            raise AppError(413, "FILE_TOO_LARGE", f"文件 {upload.filename} 为空或超过大小限制")
        digest = hashlib.sha256(content).hexdigest()
        try:
            validated = validate_upload(
                upload.filename,
                upload.content_type,
                content,
                max_uncompressed_bytes=request.app.state.settings.max_ingestion_source_bytes,
            )
        except UnsafeUploadError as exc:
            raise AppError(400, "UNSAFE_UPLOAD", str(exc)) from exc
        filename = validated.filename
        safe_name = validated.safe_filename
        suffix = Path(safe_name).suffix.casefold()
        if import_mode == "merchant_reviews" and suffix not in {".csv", ".xlsx"}:
            raise AppError(400, "INVALID_MERCHANT_IMPORT", "商家评论数据仅支持 CSV 或 XLSX 文件")
        document = await _knowledge_service(request, principal).create_document(
            DocumentInput(
                knowledge_base_id=knowledge_base_id,
                source_type="FILE",
                source_key=digest,
                display_name=filename,
                mime_type=validated.mime_type,
            )
        )
        target = (
            Path(request.app.state.settings.knowledge_data_root)
            / str(knowledge_base_id)
            / str(document.id)
            / f"{digest}-{safe_name}"
        )
        await run_in_threadpool(target.parent.mkdir, parents=True, exist_ok=True)
        await run_in_threadpool(target.write_bytes, content)
        version_prefix = "1" if import_mode == "knowledge" else "1-merchant-reviews"
        parser_version = f"{version_prefix}-{uuid7()}" if force_new_version else version_prefix
        cleaning_config: dict[str, object] = {"steps": []}
        if import_mode == "merchant_reviews":
            cleaning_config.update(
                {
                    "import_mode": "merchant_reviews",
                    "text_template": (
                        "商家'{merchant_name}'收到评分{review_rating}的评价：{review_content}"
                    ),
                }
            )
        await _knowledge_service(request, principal).create_document_version_idempotent(
            DocumentVersionInput(
                document_id=document.id,
                file_uri=str(target),
                file_sha256=digest,
                file_size=len(content),
                parser_name=target.suffix.lstrip(".") or "binary",
                parser_version=parser_version,
                cleaning_config=cleaning_config,
                splitter_config={
                    "strategy": splitter,
                    "chunk_size": chunk_size,
                    "chunk_overlap": chunk_overlap,
                },
            )
        )
        task_id = await _task_repository(request).create_with_outbox(
            task_type="INGEST",
            resource_type="DOCUMENT",
            resource_id=document.id,
            event_type="knowledge.ingest",
        )
        task_ids.append(task_id)
        file_results.append(
            {"file_name": filename, "document_id": str(document.id), "task_id": str(task_id)}
        )

    data = _accepted(task_ids[0])
    data.update({"task_ids": [str(value) for value in task_ids], "files": file_results})
    return success_response(request, data, message="accepted")


@router.get("/documents/{document_id}")
async def get_document(
    request: Request, document_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _authorize_document(request, principal, document_id, "READ")
    document = await _knowledge_service(request, principal).get_document(document_id)
    versions = await _knowledge_repository(request, principal).list_document_versions(document_id)
    data = _serialize(document)
    data["versions"] = [
        {key: str(value) if isinstance(value, UUID) else value for key, value in row.items()}
        for row in versions
    ]
    return success_response(request, data)


@router.patch("/documents/{document_id}")
async def update_document(
    request: Request,
    document_id: UUID,
    body: DocumentPatchDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    await _authorize_document(request, principal, document_id, "UPDATE")
    row = await _knowledge_service(request, principal).update_document(
        document_id, DocumentPatch(**body.model_dump())
    )
    return success_response(request, _serialize(row))


async def _create_document_task(request: Request, document_id: UUID, task_type: str) -> UUID:
    return await _task_repository(request).create_with_outbox(
        task_type=task_type,
        resource_type="DOCUMENT",
        resource_id=document_id,
        event_type=f"knowledge.{task_type.lower()}",
    )


@router.post("/documents/{document_id}/rollback", status_code=202)
async def rollback_document(
    request: Request,
    document_id: UUID,
    body: RollbackDTO,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    await _authorize_document(request, principal, document_id, "UPDATE")
    try:
        await _knowledge_service(request, principal).rollback_document(
            document_id, body.target_version_no
        )
    except InvalidRollbackTarget as exc:
        raise AppError(404, "VERSION_NOT_FOUND", "目标文档版本不存在") from exc
    task_id = await _create_document_task(request, document_id, "REBUILD")
    return success_response(request, _accepted(task_id), message="accepted")


@router.post("/documents/{document_id}/reindex", status_code=202)
async def reindex_document(
    request: Request, document_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _authorize_document(request, principal, document_id, "UPDATE")
    task_id = await _create_document_task(request, document_id, "REBUILD")
    return success_response(request, _accepted(task_id), message="accepted")


@router.delete("/documents/{document_id}", status_code=202)
async def delete_document(
    request: Request, document_id: UUID, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _authorize_document(request, principal, document_id, "DELETE")
    task_id = await _task_repository(request).delete_document_with_outbox(document_id)
    if task_id is None:
        raise AppError(404, "NOT_FOUND", "文档不存在")
    return success_response(request, _accepted(task_id), message="accepted")
