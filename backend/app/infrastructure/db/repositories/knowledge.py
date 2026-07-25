from uuid import UUID

from sqlalchemy import false, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import ColumnElement, Select

from app.application.authorization import AuthorizationPrincipal, ResourceScopeDenied, ResourceType
from app.application.knowledge import (
    DocumentInput,
    DocumentNotFound,
    DocumentPatch,
    DocumentVersionInput,
    DocumentVersionNotFound,
    DocumentVersionView,
    DocumentView,
    InvalidRollbackTarget,
    KnowledgeBaseInput,
    KnowledgeBaseNotFound,
    KnowledgeBasePatch,
    KnowledgeBaseView,
    normalize_name,
)
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase


class SQLAlchemyKnowledgeRepository:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        principal: AuthorizationPrincipal | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._principal = principal

    def scoped(self, principal: AuthorizationPrincipal) -> "SQLAlchemyKnowledgeRepository":
        """Return a request-scoped repository that enforces grants in every query."""
        return type(self)(self._session_factory, principal=principal)

    def _allowed_knowledge_base_ids(self, action: str) -> frozenset[UUID] | None:
        if self._principal is None:
            return None
        return self._principal.authorized_resource_ids(ResourceType.KNOWLEDGE_BASE, action)

    def _scope_statement(
        self,
        statement: Select,
        *,
        action: str,
        resource_id_column: ColumnElement,
    ) -> Select:
        allowed_ids = self._allowed_knowledge_base_ids(action)
        if allowed_ids is None:
            return statement
        if not allowed_ids:
            return statement.where(false())
        return statement.where(resource_id_column.in_(allowed_ids))

    def _require_tenant(self, tenant_id: UUID) -> None:
        if (
            self._principal is not None
            and not self._principal.is_platform_admin
            and self._principal.department_id != tenant_id
        ):
            raise ResourceScopeDenied("tenant scope denied")

    async def _active_knowledge_base(
        self,
        session: AsyncSession,
        knowledge_base_id: UUID,
        *,
        action: str,
        lock: bool = False,
    ) -> KnowledgeBase:
        statement = self._scope_statement(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.status != "DELETED",
            ),
            action=action,
            resource_id_column=KnowledgeBase.id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            raise KnowledgeBaseNotFound("knowledge base not found")
        return row

    async def _active_document(
        self,
        session: AsyncSession,
        document_id: UUID,
        *,
        action: str,
        lock: bool = False,
    ) -> Document:
        statement = self._scope_statement(
            select(Document).where(
                Document.id == document_id,
                Document.deleted_at.is_(None),
                Document.status != "DELETED",
            ),
            action=action,
            resource_id_column=Document.knowledge_base_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = await session.scalar(statement)
        if row is None:
            raise DocumentNotFound("document not found")
        return row

    async def create_knowledge_base(self, payload: KnowledgeBaseInput) -> KnowledgeBaseView:
        if self._principal is not None:
            self._principal.require_permission(ResourceType.KNOWLEDGE_BASE.value, "CREATE")
            self._require_tenant(payload.tenant_id)
            if (
                not self._principal.is_platform_admin
                and payload.owner_id != self._principal.user_id
            ):
                raise ResourceScopeDenied("owner scope denied")
        async with self._session_factory() as session, session.begin():
            row = KnowledgeBase(
                tenant_id=payload.tenant_id,
                owner_id=payload.owner_id,
                department_id=payload.department_id,
                name=payload.name.strip(),
                normalized_name=normalize_name(payload.name),
                description=payload.description,
                embedding_model_version_id=payload.embedding_model_version_id,
                chunk_size=payload.chunk_size,
                chunk_overlap=payload.chunk_overlap,
            )
            session.add(row)
            await session.flush()
            return _knowledge_base_view(row)

    async def list_knowledge_bases(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeBaseView]:
        self._require_tenant(tenant_id)
        async with self._session_factory() as session:
            statement = self._knowledge_base_filter_statement(
                select(KnowledgeBase),
                tenant_id,
                name=name,
                status=status,
                department_id=department_id,
                action="READ",
            )
            rows = (
                await session.scalars(
                    statement.order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [_knowledge_base_view(row) for row in rows]

    async def count_knowledge_bases(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
    ) -> int:
        self._require_tenant(tenant_id)
        async with self._session_factory() as session:
            statement = self._knowledge_base_filter_statement(
                select(func.count()).select_from(KnowledgeBase),
                tenant_id,
                name=name,
                status=status,
                department_id=department_id,
                action="READ",
            )
            return int((await session.scalar(statement)) or 0)

    def _knowledge_base_filter_statement(
        self,
        statement: Select,
        tenant_id: UUID,
        *,
        name: str | None,
        status: str | None,
        department_id: UUID | None,
        action: str,
    ) -> Select:
        statement = statement.where(KnowledgeBase.tenant_id == tenant_id)
        if status == "DELETED":
            statement = statement.where(KnowledgeBase.status == "DELETED")
        else:
            statement = statement.where(
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.status != "DELETED",
            )
            if status is not None:
                statement = statement.where(KnowledgeBase.status == status)
        if name:
            statement = statement.where(
                KnowledgeBase.normalized_name.contains(normalize_name(name))
            )
        if department_id is not None:
            statement = statement.where(KnowledgeBase.department_id == department_id)
        return self._scope_statement(
            statement,
            action=action,
            resource_id_column=KnowledgeBase.id,
        )

    async def get_knowledge_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView:
        async with self._session_factory() as session:
            return _knowledge_base_view(
                await self._active_knowledge_base(session, knowledge_base_id, action="READ")
            )

    async def update_knowledge_base(
        self, knowledge_base_id: UUID, patch: KnowledgeBasePatch
    ) -> KnowledgeBaseView:
        async with self._session_factory() as session, session.begin():
            row = await self._active_knowledge_base(
                session, knowledge_base_id, action="UPDATE", lock=True
            )
            if patch.name is not None:
                row.name = patch.name.strip()
                row.normalized_name = normalize_name(patch.name)
            if patch.description is not None:
                row.description = patch.description
            if patch.owner_id is not None:
                row.owner_id = patch.owner_id
            if patch.department_id is not None:
                row.department_id = patch.department_id
            if patch.embedding_model_id is not None:
                row.embedding_model_version_id = patch.embedding_model_id
            if patch.chunk_size is not None:
                row.chunk_size = patch.chunk_size
            if patch.chunk_overlap is not None:
                row.chunk_overlap = patch.chunk_overlap
            if patch.status is not None:
                row.status = patch.status
            await session.flush()
            return _knowledge_base_view(row)

    async def delete_knowledge_base(self, knowledge_base_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            row = await self._active_knowledge_base(
                session, knowledge_base_id, action="DELETE", lock=True
            )
            now = utc_now()
            row.status = "DELETED"
            row.deleted_at = now
            documents = (
                await session.scalars(
                    select(Document)
                    .where(
                        Document.knowledge_base_id == knowledge_base_id,
                        Document.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).all()
            for document in documents:
                document.status = "DELETED"
                document.deleted_at = now

    async def create_document(self, payload: DocumentInput) -> DocumentView:
        async with self._session_factory() as session, session.begin():
            await self._active_knowledge_base(session, payload.knowledge_base_id, action="UPDATE")
            existing = await session.scalar(
                select(Document)
                .where(
                    Document.knowledge_base_id == payload.knowledge_base_id,
                    Document.source_type == payload.source_type.strip().upper(),
                    Document.source_key == payload.source_key,
                )
                .with_for_update()
            )
            if existing is not None:
                if existing.deleted_at is not None or existing.status == "DELETED":
                    existing.deleted_at = None
                    existing.status = "UPLOADED"
                existing.display_name = payload.display_name.strip()
                existing.mime_type = payload.mime_type
                await session.flush()
                return _document_view(existing)

            row = Document(
                knowledge_base_id=payload.knowledge_base_id,
                source_type=payload.source_type.strip().upper(),
                source_key=payload.source_key,
                display_name=payload.display_name.strip(),
                mime_type=payload.mime_type,
            )
            session.add(row)
            await session.flush()
            return _document_view(row)

    async def list_documents(
        self,
        knowledge_base_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentView]:
        async with self._session_factory() as session:
            await self._active_knowledge_base(session, knowledge_base_id, action="READ")
            conditions = [
                Document.knowledge_base_id == knowledge_base_id,
                Document.deleted_at.is_(None),
                Document.status != "DELETED",
            ]
            if status:
                conditions.append(Document.status == status)
            rows = (
                await session.scalars(
                    select(Document)
                    .where(*conditions)
                    .order_by(Document.created_at.desc(), Document.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            if not rows:
                return []

            doc_ids = [d.id for d in rows]
            # Fetch file_size from current versions
            version_rows = (
                await session.execute(
                    select(DocumentVersion.document_id, DocumentVersion.file_size).where(
                        DocumentVersion.document_id.in_(doc_ids),
                        DocumentVersion.is_current.is_(True),
                    )
                )
            ).all()
            file_sizes = {r[0]: r[1] for r in version_rows}

            # Fetch chunk counts from current versions (exclude deleted chunks)
            chunk_rows = (
                await session.execute(
                    select(
                        DocumentVersion.document_id,
                        func.count(Chunk.id).label("cnt"),
                    )
                    .join(Chunk, Chunk.document_version_id == DocumentVersion.id)
                    .where(
                        DocumentVersion.document_id.in_(doc_ids),
                        DocumentVersion.is_current.is_(True),
                        Chunk.index_status != "DELETED",
                    )
                    .group_by(DocumentVersion.document_id)
                )
            ).all()
            chunk_counts = {r[0]: r[1] for r in chunk_rows}

            return [
                _document_view(
                    row,
                    file_size=file_sizes.get(row.id),
                    chunk_count=chunk_counts.get(row.id, 0),
                )
                for row in rows
            ]

    async def count_documents(self, knowledge_base_id: UUID, *, status: str | None = None) -> int:
        async with self._session_factory() as session:
            await self._active_knowledge_base(session, knowledge_base_id, action="READ")
            conditions = [
                Document.knowledge_base_id == knowledge_base_id,
                Document.deleted_at.is_(None),
                Document.status != "DELETED",
            ]
            if status:
                conditions.append(Document.status == status)
            result = await session.scalar(
                select(func.count()).select_from(Document).where(*conditions)
            )
            return result or 0

    async def get_document(self, document_id: UUID) -> DocumentView:
        async with self._session_factory() as session:
            document = await self._active_document(session, document_id, action="READ")
            # Fetch file_size and chunk_count from current version
            version_row = (
                await session.execute(
                    select(DocumentVersion.file_size, DocumentVersion.id).where(
                        DocumentVersion.document_id == document_id,
                        DocumentVersion.is_current.is_(True),
                    )
                )
            ).one_or_none()
            file_size = version_row[0] if version_row else None
            version_id = version_row[1] if version_row else None
            chunk_count = 0
            if version_id is not None:
                chunk_count = (
                    await session.scalar(
                        select(func.count())
                        .select_from(Chunk)
                        .where(
                            Chunk.document_version_id == version_id,
                            Chunk.index_status != "DELETED",
                        )
                    )
                ) or 0
            return _document_view(document, file_size=file_size, chunk_count=chunk_count)

    async def get_document_knowledge_base_id(
        self, document_id: UUID, *, action: str = "READ"
    ) -> UUID:
        async with self._session_factory() as session:
            return (
                await self._active_document(session, document_id, action=action)
            ).knowledge_base_id

    async def get_task_document_knowledge_base_id(self, document_id: UUID) -> UUID:
        """Resolve task ownership even after its document was logically deleted."""
        async with self._session_factory() as session:
            statement = self._scope_statement(
                select(Document.knowledge_base_id).where(Document.id == document_id),
                action="READ",
                resource_id_column=Document.knowledge_base_id,
            )
            knowledge_base_id = await session.scalar(statement)
            if knowledge_base_id is None:
                raise DocumentNotFound("document not found")
            return knowledge_base_id

    async def list_document_versions(self, document_id: UUID) -> list[dict[str, object]]:
        async with self._session_factory() as session:
            await self._active_document(session, document_id, action="READ")
            rows = (
                await session.scalars(
                    select(DocumentVersion)
                    .where(DocumentVersion.document_id == document_id)
                    .order_by(DocumentVersion.version_no.desc())
                )
            ).all()
            return [
                {
                    "id": row.id,
                    "version_no": row.version_no,
                    "file_uri": row.file_uri,
                    "file_sha256": row.file_sha256,
                    "file_size": row.file_size,
                    "parser_name": row.parser_name,
                    "parser_version": row.parser_version,
                    "cleaning_config": dict(row.cleaning_config_json),
                    "splitter_config": dict(row.splitter_config_json),
                    "is_current": row.is_current,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    async def update_document(self, document_id: UUID, patch: DocumentPatch) -> DocumentView:
        async with self._session_factory() as session, session.begin():
            row = await self._active_document(session, document_id, action="UPDATE", lock=True)
            if patch.display_name is not None:
                row.display_name = patch.display_name.strip()
            if patch.mime_type is not None:
                row.mime_type = patch.mime_type
            if patch.status is not None:
                row.status = patch.status
            if patch.last_error_code is not None:
                row.last_error_code = patch.last_error_code
            await session.flush()
            return _document_view(row)

    async def delete_document(self, document_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            row = await self._active_document(session, document_id, action="DELETE", lock=True)
            row.status = "DELETED"
            row.deleted_at = utc_now()

    async def create_document_version_idempotent(
        self, payload: DocumentVersionInput
    ) -> DocumentVersionView:
        async with self._session_factory() as session, session.begin():
            document = await self._active_document(
                session, payload.document_id, action="UPDATE", lock=True
            )
            existing = await session.scalar(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == payload.document_id,
                    DocumentVersion.file_sha256 == payload.file_sha256,
                    DocumentVersion.parser_name == payload.parser_name,
                    DocumentVersion.parser_version == payload.parser_version,
                )
                .order_by(DocumentVersion.version_no.desc())
                .limit(1)
                .with_for_update()
            )
            if existing is not None:
                await _mark_current_version(session, document, existing)
                return _document_version_view(existing)

            next_version_no = document.current_version_no + 1
            row = DocumentVersion(
                document_id=payload.document_id,
                version_no=next_version_no,
                file_uri=payload.file_uri,
                file_sha256=payload.file_sha256,
                file_size=payload.file_size,
                parser_name=payload.parser_name,
                parser_version=payload.parser_version,
                cleaning_config_json=payload.cleaning_config,
                splitter_config_json=payload.splitter_config,
                is_current=True,
            )
            session.add(row)
            await session.flush()
            await _mark_current_version(session, document, row)
            return _document_version_view(row)

    async def rollback_document(self, document_id: UUID, target_version_no: int) -> DocumentView:
        async with self._session_factory() as session, session.begin():
            document = await self._active_document(session, document_id, action="UPDATE", lock=True)
            target = await session.scalar(
                select(DocumentVersion)
                .where(
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.version_no == target_version_no,
                )
                .with_for_update()
            )
            if target is None:
                raise InvalidRollbackTarget("target document version does not exist")
            await _mark_current_version(session, document, target)
            document.status = "INDEXING"
            document.last_error_code = None
            await session.flush()
            return _document_view(document)


async def _mark_current_version(
    session: AsyncSession, document: Document, target: DocumentVersion
) -> None:
    if target.document_id != document.id:
        raise DocumentVersionNotFound("document version does not belong to document")
    current_versions = (
        await session.scalars(
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.is_current.is_(True),
            )
            .with_for_update()
        )
    ).all()
    for version in current_versions:
        version.is_current = version.id == target.id
    target.is_current = True
    document.current_version_no = target.version_no
    document.status = "READY"
    document.last_error_code = None


def _knowledge_base_view(row: KnowledgeBase) -> KnowledgeBaseView:
    return KnowledgeBaseView(
        id=row.id,
        tenant_id=row.tenant_id,
        owner_id=row.owner_id,
        department_id=row.department_id,
        name=row.name,
        normalized_name=row.normalized_name,
        description=row.description,
        status=row.status,
        version=row.version,
        embedding_model_version_id=row.embedding_model_version_id,
        chunk_size=row.chunk_size,
        chunk_overlap=row.chunk_overlap,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _document_view(
    row: Document, *, file_size: int | None = None, chunk_count: int = 0
) -> DocumentView:
    return DocumentView(
        id=row.id,
        knowledge_base_id=row.knowledge_base_id,
        source_type=row.source_type,
        source_key=row.source_key,
        display_name=row.display_name,
        mime_type=row.mime_type,
        status=row.status,
        current_version_no=row.current_version_no,
        last_error_code=row.last_error_code,
        version=row.version,
        file_size=file_size,
        chunk_count=chunk_count,
        created_at=row.created_at.isoformat() if row.created_at else None,
        updated_at=row.updated_at.isoformat() if row.updated_at else None,
    )


def _document_version_view(row: DocumentVersion) -> DocumentVersionView:
    return DocumentVersionView(
        id=row.id,
        document_id=row.document_id,
        version_no=row.version_no,
        file_uri=row.file_uri,
        file_sha256=row.file_sha256,
        is_current=row.is_current,
    )
