from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class KnowledgeBaseNotFound(ValueError):
    """Knowledge base is missing or has been logically deleted."""


class DocumentNotFound(ValueError):
    """Document is missing or has been logically deleted."""


class DocumentVersionNotFound(ValueError):
    """The requested immutable document version does not exist."""


class InvalidRollbackTarget(ValueError):
    """The requested rollback target does not belong to the document."""


@dataclass(frozen=True, slots=True)
class KnowledgeBaseInput:
    owner_id: UUID
    name: str
    embedding_model_version_id: UUID
    tenant_id: UUID
    department_id: UUID | None = None
    description: str | None = None
    chunk_size: int = 500
    chunk_overlap: int = 80


@dataclass(frozen=True, slots=True)
class KnowledgeBasePatch:
    name: str | None = None
    description: str | None = None
    owner_id: UUID | None = None
    embedding_model_id: UUID | None = None
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    status: str | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeBaseView:
    id: UUID
    owner_id: UUID
    name: str
    normalized_name: str
    status: str
    version: int
    tenant_id: UUID
    department_id: UUID | None = None
    description: str | None = None
    embedding_model_version_id: UUID | None = None
    chunk_size: int = 0
    chunk_overlap: int = 0
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentInput:
    knowledge_base_id: UUID
    source_type: str
    source_key: str
    display_name: str
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentPatch:
    display_name: str | None = None
    mime_type: str | None = None
    status: str | None = None
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentView:
    id: UUID
    knowledge_base_id: UUID
    source_type: str
    source_key: str
    display_name: str
    status: str
    current_version_no: int
    version: int
    mime_type: str | None = None
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentVersionInput:
    document_id: UUID
    file_uri: str
    file_sha256: str
    file_size: int
    parser_name: str
    parser_version: str
    cleaning_config: dict[str, object]
    splitter_config: dict[str, object]


@dataclass(frozen=True, slots=True)
class DocumentVersionView:
    id: UUID
    document_id: UUID
    version_no: int
    file_uri: str
    file_sha256: str
    is_current: bool


class KnowledgeRepository(Protocol):
    async def create_knowledge_base(self, payload: KnowledgeBaseInput) -> KnowledgeBaseView: ...

    async def list_knowledge_bases(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeBaseView]: ...

    async def count_knowledge_bases(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
    ) -> int: ...

    async def get_knowledge_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView: ...

    async def update_knowledge_base(
        self, knowledge_base_id: UUID, patch: KnowledgeBasePatch
    ) -> KnowledgeBaseView: ...

    async def delete_knowledge_base(self, knowledge_base_id: UUID) -> None: ...

    async def create_document(self, payload: DocumentInput) -> DocumentView: ...

    async def list_documents(
        self, knowledge_base_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[DocumentView]: ...

    async def get_document(self, document_id: UUID) -> DocumentView: ...

    async def update_document(self, document_id: UUID, patch: DocumentPatch) -> DocumentView: ...

    async def delete_document(self, document_id: UUID) -> None: ...

    async def create_document_version_idempotent(
        self, payload: DocumentVersionInput
    ) -> DocumentVersionView: ...

    async def rollback_document(
        self, document_id: UUID, target_version_no: int
    ) -> DocumentView: ...


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    async def create_knowledge_base(self, payload: KnowledgeBaseInput) -> KnowledgeBaseView:
        _validate_name(payload.name)
        _validate_chunking(payload.chunk_size, payload.chunk_overlap)
        return await self._repository.create_knowledge_base(payload)

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
        return await self._repository.list_knowledge_bases(
            tenant_id,
            name=name.strip() if name else None,
            status=status,
            department_id=department_id,
            limit=_validate_limit(limit),
            offset=_validate_offset(offset),
        )

    async def count_knowledge_bases(
        self,
        tenant_id: UUID,
        *,
        name: str | None = None,
        status: str | None = None,
        department_id: UUID | None = None,
    ) -> int:
        return await self._repository.count_knowledge_bases(
            tenant_id,
            name=name.strip() if name else None,
            status=status,
            department_id=department_id,
        )

    async def get_knowledge_base(self, knowledge_base_id: UUID) -> KnowledgeBaseView:
        return await self._repository.get_knowledge_base(knowledge_base_id)

    async def update_knowledge_base(
        self, knowledge_base_id: UUID, patch: KnowledgeBasePatch
    ) -> KnowledgeBaseView:
        if patch.name is not None:
            _validate_name(patch.name)
        if patch.chunk_size is not None or patch.chunk_overlap is not None:
            _validate_patch_chunking(patch)
        return await self._repository.update_knowledge_base(knowledge_base_id, patch)

    async def delete_knowledge_base(self, knowledge_base_id: UUID) -> None:
        await self._repository.delete_knowledge_base(knowledge_base_id)

    async def create_document(self, payload: DocumentInput) -> DocumentView:
        if not payload.source_type.strip() or not payload.source_key.strip():
            raise ValueError("document source must not be empty")
        _validate_name(payload.display_name)
        return await self._repository.create_document(payload)

    async def list_documents(
        self, knowledge_base_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[DocumentView]:
        return await self._repository.list_documents(
            knowledge_base_id, limit=_validate_limit(limit), offset=_validate_offset(offset)
        )

    async def get_document(self, document_id: UUID) -> DocumentView:
        return await self._repository.get_document(document_id)

    async def update_document(self, document_id: UUID, patch: DocumentPatch) -> DocumentView:
        if patch.display_name is not None:
            _validate_name(patch.display_name)
        return await self._repository.update_document(document_id, patch)

    async def delete_document(self, document_id: UUID) -> None:
        await self._repository.delete_document(document_id)

    async def create_document_version_idempotent(
        self, payload: DocumentVersionInput
    ) -> DocumentVersionView:
        if len(payload.file_sha256) != 64:
            raise ValueError("file_sha256 must be a 64-character hex digest")
        if payload.file_size <= 0:
            raise ValueError("file_size must be positive")
        return await self._repository.create_document_version_idempotent(payload)

    async def rollback_document(self, document_id: UUID, target_version_no: int) -> DocumentView:
        if target_version_no <= 0:
            raise ValueError("target_version_no must be positive")
        return await self._repository.rollback_document(document_id, target_version_no)


def normalize_name(value: str) -> str:
    normalized = " ".join(value.strip().casefold().split())
    if not normalized:
        raise ValueError("name must not be empty")
    return normalized


def _validate_name(value: str) -> None:
    normalize_name(value)


def _validate_chunking(chunk_size: int, chunk_overlap: int) -> None:
    if not 100 <= chunk_size <= 4000:
        raise ValueError("chunk_size must be between 100 and 4000")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size")


def _validate_patch_chunking(patch: KnowledgeBasePatch) -> None:
    if patch.chunk_size is not None and not 100 <= patch.chunk_size <= 4000:
        raise ValueError("chunk_size must be between 100 and 4000")
    if patch.chunk_overlap is not None and patch.chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative")


def _validate_limit(value: int) -> int:
    if not 1 <= value <= 200:
        raise ValueError("limit must be between 1 and 200")
    return value


def _validate_offset(value: int) -> int:
    if value < 0:
        raise ValueError("offset must be non-negative")
    return value
