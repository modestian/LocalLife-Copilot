from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
from app.infrastructure.db.models.knowledge import Document, DocumentVersion, KnowledgeBase


class SQLAlchemyKnowledgeRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create_knowledge_base(self, payload: KnowledgeBaseInput) -> KnowledgeBaseView:
        async with self._session_factory() as session, session.begin():
            row = KnowledgeBase(
                owner_id=payload.owner_id,
                department_id=payload.department_id,
                tenant_id=payload.tenant_id,
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
        self, *, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeBaseView]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(KnowledgeBase)
                    .where(KnowledgeBase.deleted_at.is_(None), KnowledgeBase.status != "DELETED")
                    .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
                        return [_knowledge_base_view(row) for row in rows]

    async def update_knowledge_base(
        self, knowledge_base_id: UUID, patch: KnowledgeBasePatch
    ) -> KnowledgeBaseView:
        async with self._session_factory() as session, session.begin():
            row = await _active_knowledge_base(session, knowledge_base_id, lock=True)
            if patch.name is not None:
                row.name = patch.name.strip()
                row.normalized_name = normalize_name(patch.name)
            if patch.description is not None:
                row.description = patch.description
            if patch.chunk_size is not None:
                row.chunk_size = patch.chunk_size
            if patch.chunk_overlap is not None:
                row.chunk_overlap = patch.chunk_overlap
            if patch.tenant_id is not None:
                row.tenant_id = patch.tenant_id
            if patch.department_id is not None:
                row.department_id = patch.department_id
            if patch.status is not None:
                row.status = patch.status
            await session.flush()
            return _knowledge_base_view(row)

    async def delete_knowledge_base(self, knowledge_base_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            row = await _active_knowledge_base(session, knowledge_base_id, lock=True)
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
            await _active_knowledge_base(session, payload.knowledge_base_id)
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
        self, knowledge_base_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[DocumentView]:
        async with self._session_factory() as session:
            await _active_knowledge_base(session, knowledge_base_id)
            rows = (
                await session.scalars(
                    select(Document)
                    .where(
                        Document.knowledge_base_id == knowledge_base_id,
                        Document.deleted_at.is_(None),
                        Document.status != "DELETED",
                    )
                    .order_by(Document.created_at.desc(), Document.id)
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
            return [_document_view(row) for row in rows]

    async def update_document(self, document_id: UUID, patch: DocumentPatch) -> DocumentView:
        async with self._session_factory() as session, session.begin():
            row = await _active_document(session, document_id, lock=True)
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
            row = await _active_document(session, document_id, lock=True)
            row.status = "DELETED"
            row.deleted_at = utc_now()

    async def create_document_version_idempotent(
        self, payload: DocumentVersionInput
    ) -> DocumentVersionView:
        async with self._session_factory() as session, session.begin():
            document = await _active_document(session, payload.document_id, lock=True)
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
            document = await _active_document(session, document_id, lock=True)
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


async def _active_knowledge_base(
    session: AsyncSession, knowledge_base_id: UUID, *, lock: bool = False
) -> KnowledgeBase:
    statement = select(KnowledgeBase).where(
        KnowledgeBase.id == knowledge_base_id,
        KnowledgeBase.deleted_at.is_(None),
        KnowledgeBase.status != "DELETED",
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise KnowledgeBaseNotFound("knowledge base not found")
    return row


async def _active_document(
    session: AsyncSession, document_id: UUID, *, lock: bool = False
) -> Document:
    statement = select(Document).where(
        Document.id == document_id,
        Document.deleted_at.is_(None),
        Document.status != "DELETED",
    )
    if lock:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise DocumentNotFound("document not found")
    return row


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
        owner_id=row.owner_id,
        department_id=row.department_id,
        tenant_id=row.tenant_id,
        name=row.name,
        normalized_name=row.normalized_name,
        description=row.description,
        status=row.status,
        version=row.version,
    )


def _document_view(row: Document) -> DocumentView:
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
