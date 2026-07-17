from uuid import UUID

import pytest

from app.application.knowledge import (
    DocumentInput,
    DocumentNotFound,
    DocumentPatch,
    DocumentVersionInput,
    DocumentVersionView,
    DocumentView,
    InvalidRollbackTarget,
    KnowledgeBaseInput,
    KnowledgeBaseNotFound,
    KnowledgeBasePatch,
    KnowledgeBaseView,
    KnowledgeService,
    normalize_name,
)
from app.core.ids import uuid7


class InMemoryKnowledgeRepository:
    def __init__(self) -> None:
        self.knowledge_bases: dict[UUID, KnowledgeBaseView] = {}
        self.documents: dict[UUID, DocumentView] = {}
        self.versions: dict[UUID, list[DocumentVersionView]] = {}

    async def create_knowledge_base(self, payload: KnowledgeBaseInput) -> KnowledgeBaseView:
        row = KnowledgeBaseView(
            id=uuid7(),
            owner_id=payload.owner_id,
            department_id=payload.department_id,
            name=payload.name.strip(),
            normalized_name=normalize_name(payload.name),
            description=payload.description,
            status="ACTIVE",
            version=1,
        )
        self.knowledge_bases[row.id] = row
        return row

    async def list_knowledge_bases(
        self, *, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeBaseView]:
        rows = [row for row in self.knowledge_bases.values() if row.status != "DELETED"]
        return rows[offset : offset + limit]

    async def update_knowledge_base(
        self, knowledge_base_id: UUID, patch: KnowledgeBasePatch
    ) -> KnowledgeBaseView:
        row = self._knowledge_base(knowledge_base_id)
        name = patch.name.strip() if patch.name is not None else row.name
        normalized_name = (
            normalize_name(patch.name) if patch.name is not None else row.normalized_name
        )
        updated = KnowledgeBaseView(
            id=row.id,
            owner_id=row.owner_id,
            department_id=row.department_id,
            name=name,
            normalized_name=normalized_name,
            description=patch.description if patch.description is not None else row.description,
            status=patch.status if patch.status is not None else row.status,
            version=row.version + 1,
        )
        self.knowledge_bases[row.id] = updated
        return updated

    async def delete_knowledge_base(self, knowledge_base_id: UUID) -> None:
        row = self._knowledge_base(knowledge_base_id)
        self.knowledge_bases[row.id] = KnowledgeBaseView(
            id=row.id,
            owner_id=row.owner_id,
            department_id=row.department_id,
            name=row.name,
            normalized_name=row.normalized_name,
            description=row.description,
            status="DELETED",
            version=row.version + 1,
        )

    async def create_document(self, payload: DocumentInput) -> DocumentView:
        self._knowledge_base(payload.knowledge_base_id)
        source_type = payload.source_type.strip().upper()
        for row in self.documents.values():
            if (
                row.knowledge_base_id == payload.knowledge_base_id
                and row.source_type == source_type
                and row.source_key == payload.source_key
            ):
                updated = DocumentView(
                    id=row.id,
                    knowledge_base_id=row.knowledge_base_id,
                    source_type=row.source_type,
                    source_key=row.source_key,
                    display_name=payload.display_name.strip(),
                    mime_type=payload.mime_type,
                    status="UPLOADED",
                    current_version_no=row.current_version_no,
                    last_error_code=row.last_error_code,
                    version=row.version + 1,
                )
                self.documents[row.id] = updated
                return updated
        row = DocumentView(
            id=uuid7(),
            knowledge_base_id=payload.knowledge_base_id,
            source_type=source_type,
            source_key=payload.source_key,
            display_name=payload.display_name.strip(),
            mime_type=payload.mime_type,
            status="UPLOADED",
            current_version_no=0,
            last_error_code=None,
            version=1,
        )
        self.documents[row.id] = row
        return row

    async def list_documents(
        self, knowledge_base_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[DocumentView]:
        self._knowledge_base(knowledge_base_id)
        rows = [
            row
            for row in self.documents.values()
            if row.knowledge_base_id == knowledge_base_id and row.status != "DELETED"
        ]
        return rows[offset : offset + limit]

    async def update_document(self, document_id: UUID, patch: DocumentPatch) -> DocumentView:
        row = self._document(document_id)
        display_name = (
            patch.display_name.strip() if patch.display_name is not None else row.display_name
        )
        updated = DocumentView(
            id=row.id,
            knowledge_base_id=row.knowledge_base_id,
            source_type=row.source_type,
            source_key=row.source_key,
            display_name=display_name,
            mime_type=patch.mime_type if patch.mime_type is not None else row.mime_type,
            status=patch.status if patch.status is not None else row.status,
            current_version_no=row.current_version_no,
            last_error_code=patch.last_error_code
            if patch.last_error_code is not None
            else row.last_error_code,
            version=row.version + 1,
        )
        self.documents[row.id] = updated
        return updated

    async def delete_document(self, document_id: UUID) -> None:
        row = self._document(document_id)
        self.documents[row.id] = DocumentView(
            id=row.id,
            knowledge_base_id=row.knowledge_base_id,
            source_type=row.source_type,
            source_key=row.source_key,
            display_name=row.display_name,
            mime_type=row.mime_type,
            status="DELETED",
            current_version_no=row.current_version_no,
            last_error_code=row.last_error_code,
            version=row.version + 1,
        )

    async def create_document_version_idempotent(
        self, payload: DocumentVersionInput
    ) -> DocumentVersionView:
        document = self._document(payload.document_id)
        versions = self.versions.setdefault(document.id, [])
        for row in versions:
            if row.file_sha256 == payload.file_sha256:
                self._set_document_current(document, row.version_no)
                return row
        row = DocumentVersionView(
            id=uuid7(),
            document_id=document.id,
            version_no=document.current_version_no + 1,
            file_uri=payload.file_uri,
            file_sha256=payload.file_sha256,
            is_current=True,
        )
        versions.append(row)
        self._set_document_current(document, row.version_no)
        return row

    async def rollback_document(self, document_id: UUID, target_version_no: int) -> DocumentView:
        document = self._document(document_id)
        if target_version_no not in {row.version_no for row in self.versions.get(document_id, [])}:
            raise InvalidRollbackTarget("target document version does not exist")
        self._set_document_current(document, target_version_no, status="INDEXING")
        return self.documents[document_id]

    def _knowledge_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView:
        row = self.knowledge_bases.get(knowledge_base_id)
        if row is None or row.status == "DELETED":
            raise KnowledgeBaseNotFound("knowledge base not found")
        return row

    def _document(self, document_id: UUID) -> DocumentView:
        row = self.documents.get(document_id)
        if row is None or row.status == "DELETED":
            raise DocumentNotFound("document not found")
        return row

    def _set_document_current(
        self, document: DocumentView, version_no: int, *, status: str = "READY"
    ) -> None:
        self.versions[document.id] = [
            DocumentVersionView(
                id=row.id,
                document_id=row.document_id,
                version_no=row.version_no,
                file_uri=row.file_uri,
                file_sha256=row.file_sha256,
                is_current=row.version_no == version_no,
            )
            for row in self.versions[document.id]
        ]
        self.documents[document.id] = DocumentView(
            id=document.id,
            knowledge_base_id=document.knowledge_base_id,
            source_type=document.source_type,
            source_key=document.source_key,
            display_name=document.display_name,
            mime_type=document.mime_type,
            status=status,
            current_version_no=version_no,
            last_error_code=None,
            version=document.version + 1,
        )


@pytest.mark.asyncio
async def test_knowledge_base_crud_and_logical_delete() -> None:
    service = KnowledgeService(InMemoryKnowledgeRepository())
    created = await service.create_knowledge_base(
        KnowledgeBaseInput(
            owner_id=uuid7(),
            name="  Menu Docs  ",
            embedding_model_version_id=uuid7(),
        )
    )

    assert created.name == "Menu Docs"
    assert created.normalized_name == "menu docs"
    updated = await service.update_knowledge_base(
        created.id, KnowledgeBasePatch(name="Menu Knowledge", description="curated")
    )
    assert updated.normalized_name == "menu knowledge"

    await service.delete_knowledge_base(created.id)

    assert await service.list_knowledge_bases() == []
    with pytest.raises(KnowledgeBaseNotFound):
        await service.list_documents(created.id)


@pytest.mark.asyncio
async def test_document_crud_is_idempotent_by_source_and_logically_deletes() -> None:
    repository = InMemoryKnowledgeRepository()
    service = KnowledgeService(repository)
    kb = await service.create_knowledge_base(
        KnowledgeBaseInput(owner_id=uuid7(), name="KB", embedding_model_version_id=uuid7())
    )

    first = await service.create_document(
        DocumentInput(kb.id, "file", "menus.csv", "Menus", "text/csv")
    )
    second = await service.create_document(
        DocumentInput(kb.id, "FILE", "menus.csv", "Menus renamed", "text/csv")
    )
    renamed = await service.update_document(first.id, DocumentPatch(display_name="Menus v2"))

    assert second.id == first.id
    assert second.display_name == "Menus renamed"
    assert renamed.display_name == "Menus v2"

    await service.delete_document(first.id)

    assert await service.list_documents(kb.id) == []
    with pytest.raises(DocumentNotFound):
        await service.update_document(first.id, DocumentPatch(display_name="hidden"))


@pytest.mark.asyncio
async def test_document_version_writes_are_idempotent_and_can_rollback() -> None:
    service = KnowledgeService(InMemoryKnowledgeRepository())
    kb = await service.create_knowledge_base(
        KnowledgeBaseInput(owner_id=uuid7(), name="KB", embedding_model_version_id=uuid7())
    )
    document = await service.create_document(DocumentInput(kb.id, "file", "guide.md", "Guide"))
    version_input = DocumentVersionInput(
        document_id=document.id,
        file_uri="file:///guide.md",
        file_sha256="a" * 64,
        file_size=128,
        parser_name="markdown",
        parser_version="1.0",
        cleaning_config={},
        splitter_config={"strategy": "recursive"},
    )

    first = await service.create_document_version_idempotent(version_input)
    repeated = await service.create_document_version_idempotent(version_input)
    second = await service.create_document_version_idempotent(
        DocumentVersionInput(
            document_id=document.id,
            file_uri="file:///guide-v2.md",
            file_sha256="b" * 64,
            file_size=256,
            parser_name="markdown",
            parser_version="1.0",
            cleaning_config={},
            splitter_config={"strategy": "recursive"},
        )
    )
    rolled_back = await service.rollback_document(document.id, first.version_no)

    assert repeated.id == first.id
    assert second.version_no == 2
    assert rolled_back.current_version_no == 1
    assert rolled_back.status == "INDEXING"


@pytest.mark.asyncio
async def test_service_rejects_invalid_payloads() -> None:
    service = KnowledgeService(InMemoryKnowledgeRepository())

    with pytest.raises(ValueError, match="name"):
        await service.create_knowledge_base(
            KnowledgeBaseInput(owner_id=uuid7(), name=" ", embedding_model_version_id=uuid7())
        )
    with pytest.raises(ValueError, match="chunk_size"):
        await service.create_knowledge_base(
            KnowledgeBaseInput(
                owner_id=uuid7(),
                name="KB",
                embedding_model_version_id=uuid7(),
                chunk_size=10,
            )
        )
    with pytest.raises(ValueError, match="file_sha256"):
        await service.create_document_version_idempotent(
            DocumentVersionInput(
                document_id=uuid7(),
                file_uri="file:///bad",
                file_sha256="short",
                file_size=1,
                parser_name="text",
                parser_version="1",
                cleaning_config={},
                splitter_config={},
            )
        )
