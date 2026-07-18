import hashlib
from dataclasses import replace
from io import BytesIO
from uuid import UUID

import pytest

from app.etl.embeddings import EmbeddingError
from app.etl.lifecycle import (
    LifecycleError,
    LifecycleJob,
    ProjectionCountMismatch,
    SourceFileTooLarge,
    TaskOperation,
    TaskStage,
    WorkerLifecycleService,
    projection_id,
)
from app.etl.models import ChunkRecord

TASK_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b121")
TENANT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b124")
KNOWLEDGE_BASE_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b125")
DOCUMENT_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b122")
VERSION_ID = UUID("0190c4d2-7f20-7b31-9f75-8f6cc8e2b123")


class MemoryStorage:
    def __init__(self, content: bytes = "第一段。第二段。".encode()) -> None:
        self.content = content

    def open(self, uri: str) -> BytesIO:
        assert uri == "memory://document"
        return BytesIO(self.content)


class TrackingStorage:
    def __init__(self, content: bytes) -> None:
        self.stream = TrackingStream(content)

    def open(self, uri: str) -> BytesIO:
        assert uri == "memory://document"
        return self.stream


class TrackingStream(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


class MemoryProjection:
    def __init__(self) -> None:
        self.chunks: dict[UUID, list[ChunkRecord]] = {}
        self.deleted_versions: list[UUID] = []
        self.reported_count: int | None = None

    def upsert(self, document_version_id: UUID, chunks: list[ChunkRecord]) -> None:
        self.chunks[document_version_id] = list(chunks)

    def delete(self, document_version_id: UUID) -> int:
        self.deleted_versions.append(document_version_id)
        return len(self.chunks.pop(document_version_id, []))

    def count(self, document_version_id: UUID) -> int:
        if self.reported_count is not None:
            return self.reported_count
        return len(self.chunks.get(document_version_id, []))


class MemoryRepository:
    def __init__(self, job: LifecycleJob) -> None:
        self.job = job
        self.claimed = False
        self.cancel_requested = False
        self.progress: list[tuple[TaskStage, int]] = []
        self.chunks: dict[UUID, list[ChunkRecord]] = {}
        self.indexed_ids: list[str] = []
        self.ready: tuple[UUID, UUID, int] | None = None
        self.failed: tuple[str, str] | None = None
        self.document_error: str | None = None
        self.completed: dict[str, object] | None = None
        self.cancelled = False
        self.deleted_versions: list[UUID] = []
        self.retry_operation: TaskOperation | None = None

    def claim(
        self, task_id: UUID, operation: TaskOperation, *, worker_id: str
    ) -> LifecycleJob | None:
        assert worker_id == "worker-test"
        assert task_id == self.job.task_id
        assert operation == self.job.operation
        if self.claimed:
            return None
        self.claimed = True
        return self.job

    def update_progress(self, task_id: UUID, stage: TaskStage, progress: int) -> None:
        assert task_id == TASK_ID
        self.progress.append((stage, progress))

    def cancellation_requested(self, task_id: UUID) -> bool:
        assert task_id == TASK_ID
        return self.cancel_requested

    def request_cancel(self, task_id: UUID) -> bool:
        assert task_id == TASK_ID
        self.cancel_requested = True
        return True

    def prepare_retry(self, task_id: UUID) -> TaskOperation | None:
        assert task_id == TASK_ID
        return self.retry_operation

    def replace_chunks(self, document_version_id: UUID, chunks: list[ChunkRecord]) -> None:
        self.chunks[document_version_id] = list(chunks)

    def chunks_for_version(self, document_version_id: UUID) -> list[ChunkRecord]:
        return self.chunks.get(document_version_id, [])

    def mark_chunks_indexed(self, document_version_id: UUID, projection_ids: list[str]) -> None:
        assert document_version_id == VERSION_ID
        self.indexed_ids = list(projection_ids)

    def mark_chunks_deleted(self, document_version_id: UUID) -> None:
        self.deleted_versions.append(document_version_id)

    def mark_document_ready(
        self, document_id: UUID, document_version_id: UUID, chunk_count: int
    ) -> None:
        self.ready = (document_id, document_version_id, chunk_count)

    def mark_document_failed(self, document_id: UUID, error_code: str) -> None:
        assert document_id == DOCUMENT_ID
        self.document_error = error_code

    def complete_task(self, task_id: UUID, result: dict[str, object]) -> None:
        assert task_id == TASK_ID
        self.completed = dict(result)

    def fail_task(self, task_id: UUID, error_code: str, error_message: str) -> None:
        assert task_id == TASK_ID
        self.failed = (error_code, error_message)

    def cancel_task(self, task_id: UUID) -> None:
        assert task_id == TASK_ID
        self.cancelled = True


def make_job(operation: TaskOperation = TaskOperation.INGEST) -> LifecycleJob:
    return LifecycleJob(
        task_id=TASK_ID,
        operation=operation,
        tenant_id=TENANT_ID,
        knowledge_base_id=KNOWLEDGE_BASE_ID,
        document_id=DOCUMENT_ID,
        document_version_id=VERSION_ID,
        source_uri="memory://document" if operation is TaskOperation.INGEST else None,
        source_key="document.txt" if operation is TaskOperation.INGEST else None,
        metadata={
            "tenant_id": "spoofed-tenant",
            "knowledge_base_id": "spoofed-kb",
            "document_id": "spoofed-document",
            "resource_scope": ["PUBLIC"],
        },
        splitter_config={"strategy": "recursive", "chunk_size": 100, "chunk_overlap": 0},
    )


def make_service(
    repository: MemoryRepository, projection: MemoryProjection
) -> tuple[WorkerLifecycleService, list[tuple[TaskOperation, UUID]]]:
    dispatched: list[tuple[TaskOperation, UUID]] = []
    service = WorkerLifecycleService(
        repository,
        MemoryStorage(),
        projection,
        lambda operation, task_id: dispatched.append((operation, task_id)),
        worker_id="worker-test",
    )
    return service, dispatched


def test_ingest_persists_projects_verifies_then_marks_document_ready() -> None:
    repository = MemoryRepository(make_job())
    projection = MemoryProjection()
    service, _ = make_service(repository, projection)

    result = service.ingest(TASK_ID)

    assert result.status == "SUCCEEDED"
    assert repository.ready == (DOCUMENT_ID, VERSION_ID, 1)
    assert repository.indexed_ids == [projection_id(VERSION_ID, 0)]
    assert repository.completed is not None
    assert repository.completed["document_version_id"] == str(VERSION_ID)
    assert repository.completed["chunk_count"] == 1
    metadata = repository.chunks[VERSION_ID][0].metadata
    assert metadata["tenant_id"] == str(TENANT_ID)
    assert metadata["knowledge_base_id"] == str(KNOWLEDGE_BASE_ID)
    assert metadata["document_id"] == str(DOCUMENT_ID)
    assert metadata["resource_scope"] == [f"KNOWLEDGE_BASE:{KNOWLEDGE_BASE_ID}"]
    assert repository.completed["cleaning_report"]["input_count"] == 1
    assert repository.completed["splitting_report"]["strategy"] == "recursive"
    assert repository.completed["source_validation"]["size_bytes"] == len(MemoryStorage().content)
    assert [stage for stage, _ in repository.progress] == [
        TaskStage.LOADING,
        TaskStage.CLEANING,
        TaskStage.SPLITTING,
        TaskStage.PERSISTING,
        TaskStage.INDEXING,
        TaskStage.VERIFYING,
    ]


def test_ingest_honours_cancellation_before_non_interruptible_stages() -> None:
    repository = MemoryRepository(make_job())
    repository.cancel_requested = True
    service, _ = make_service(repository, MemoryProjection())

    result = service.ingest(TASK_ID)

    assert result.status == "CANCELLED"
    assert repository.cancelled is True
    assert repository.chunks == {}
    assert repository.ready is None


def test_projection_count_mismatch_fails_task_and_document() -> None:
    repository = MemoryRepository(make_job())
    projection = MemoryProjection()
    projection.reported_count = 0
    service, _ = make_service(repository, projection)

    with pytest.raises(ProjectionCountMismatch):
        service.ingest(TASK_ID)

    assert repository.failed is not None
    assert repository.failed[0] == "PROJECTION_COUNT_MISMATCH"
    assert repository.document_error == "PROJECTION_COUNT_MISMATCH"
    assert repository.ready is None


def test_embedding_failure_persists_specific_failure_code() -> None:
    class FailingProjection(MemoryProjection):
        def upsert(self, document_version_id: UUID, chunks: list[ChunkRecord]) -> None:
            raise EmbeddingError("EMBEDDING_DIMENSION_MISMATCH", "wrong vector dimension")

    repository = MemoryRepository(make_job())
    service, _ = make_service(repository, FailingProjection())

    with pytest.raises(EmbeddingError):
        service.ingest(TASK_ID)

    assert repository.failed == ("EMBEDDING_DIMENSION_MISMATCH", "wrong vector dimension")
    assert repository.document_error == "EMBEDDING_DIMENSION_MISMATCH"
    assert repository.ready is None


def test_delete_removes_projection_before_marking_chunks_deleted() -> None:
    repository = MemoryRepository(make_job(TaskOperation.DELETE))
    projection = MemoryProjection()
    projection.chunks[VERSION_ID] = []
    service, _ = make_service(repository, projection)

    result = service.delete(TASK_ID)

    assert result.status == "SUCCEEDED"
    assert projection.deleted_versions == [VERSION_ID]
    assert repository.deleted_versions == [VERSION_ID]
    assert repository.document_error is None


def test_rebuild_reuses_existing_version_and_chunks() -> None:
    repository = MemoryRepository(make_job(TaskOperation.REBUILD))
    ingest_repository = MemoryRepository(make_job())
    ingest_projection = MemoryProjection()
    ingest_service, _ = make_service(ingest_repository, ingest_projection)
    ingest_service.ingest(TASK_ID)
    repository.chunks[VERSION_ID] = ingest_repository.chunks[VERSION_ID]
    projection = MemoryProjection()
    service, _ = make_service(repository, projection)

    result = service.rebuild(TASK_ID)

    assert result.details["document_version_id"] == str(VERSION_ID)
    assert projection.deleted_versions == [VERSION_ID]
    assert repository.ready == (DOCUMENT_ID, VERSION_ID, 1)


def test_retry_dispatches_original_operation_without_creating_a_job() -> None:
    repository = MemoryRepository(make_job())
    repository.retry_operation = TaskOperation.REBUILD
    service, dispatched = make_service(repository, MemoryProjection())

    result = service.retry(TASK_ID)

    assert result.status == "PENDING"
    assert dispatched == [(TaskOperation.REBUILD, TASK_ID)]
    assert repository.claimed is False


def test_invalid_source_persists_explicit_failure_code() -> None:
    repository = MemoryRepository(make_job())
    service = WorkerLifecycleService(
        repository,
        MemoryStorage(b"\xff"),
        MemoryProjection(),
        lambda operation, task_id: None,
        worker_id="worker-test",
    )

    with pytest.raises(ValueError):
        service.ingest(TASK_ID)

    assert repository.failed is not None
    assert repository.failed[0] == "FILE_LOAD_FAILED"


def test_oversize_source_persists_explicit_failure_code_and_reason() -> None:
    repository = MemoryRepository(replace(make_job(), max_source_bytes=4))
    service, _ = make_service(repository, MemoryProjection())

    with pytest.raises(SourceFileTooLarge, match="4 bytes"):
        service.ingest(TASK_ID)

    assert repository.failed == (
        "FILE_TOO_LARGE",
        "source exceeds the maximum allowed size of 4 bytes",
    )
    assert repository.document_error == "FILE_TOO_LARGE"
    assert repository.chunks == {}


def test_source_hash_size_and_mime_are_verified_before_loading() -> None:
    payload = "第一段。第二段。".encode()
    job = replace(
        make_job(),
        source_sha256=hashlib.sha256(payload).hexdigest(),
        source_size_bytes=len(payload),
        mime_type="text/plain",
    )
    repository = MemoryRepository(job)
    projection = MemoryProjection()
    service = WorkerLifecycleService(
        repository,
        MemoryStorage(payload),
        projection,
        lambda operation, task_id: None,
        worker_id="worker-test",
    )

    result = service.ingest(TASK_ID)

    assert result.details["source_validation"] == {
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "mime_type": "text/plain",
    }


def test_source_validation_reads_storage_in_bounded_blocks() -> None:
    payload = b"a" * (64 * 1024 + 1)
    storage = TrackingStorage(payload)
    repository = MemoryRepository(make_job())
    service = WorkerLifecycleService(
        repository,
        storage,
        MemoryProjection(),
        lambda operation, task_id: None,
        worker_id="worker-test",
    )

    service.ingest(TASK_ID)

    assert storage.stream.read_sizes
    assert all(0 < size <= 64 * 1024 for size in storage.stream.read_sizes)


@pytest.mark.parametrize(
    ("changes", "error_code"),
    [
        ({"source_sha256": "0" * 64}, "FILE_HASH_MISMATCH"),
        ({"source_size_bytes": 1}, "FILE_SIZE_MISMATCH"),
        ({"mime_type": "application/pdf"}, "FILE_MIME_MISMATCH"),
    ],
)
def test_source_metadata_mismatch_fails_before_chunk_persistence(
    changes: dict[str, object], error_code: str
) -> None:
    repository = MemoryRepository(replace(make_job(), **changes))
    service, _ = make_service(repository, MemoryProjection())

    with pytest.raises(LifecycleError, match="source"):
        service.ingest(TASK_ID)

    assert repository.failed is not None
    assert repository.failed[0] == error_code
    assert repository.chunks == {}


def test_worker_registers_handlers_and_dispatches_allowlisted_operation(monkeypatch) -> None:
    from app.worker import celery_app, dispatch_lifecycle_task

    expected = {
        "knowledge.ingest",
        "knowledge.retry",
        "knowledge.cancel",
        "knowledge.delete",
        "knowledge.rebuild",
    }
    sent: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(
        celery_app,
        "send_task",
        lambda name, args: sent.append((name, args)),
    )

    dispatch_lifecycle_task(TaskOperation.REBUILD, TASK_ID)

    assert expected <= set(celery_app.tasks)
    assert sent == [("knowledge.rebuild", [str(TASK_ID)])]


def test_worker_builds_production_adapters_around_repository(monkeypatch) -> None:
    import app.worker as worker

    client = object()
    storage = object()
    projection = object()
    embedder = object()
    service = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(worker, "OpenSearch", lambda url: client)
    monkeypatch.setattr(worker, "LocalSourceStorage", lambda root: storage)
    monkeypatch.setattr(worker, "HttpEmbeddingProvider", lambda *args, **kwargs: object())
    monkeypatch.setattr(worker, "BatchedEmbedder", lambda *args, **kwargs: embedder)
    monkeypatch.setattr(
        worker, "OpenSearchProjection", lambda value, index, value_embedder: projection
    )

    def fake_service(repository, source, search_projection, dispatcher, **options):
        captured.update(
            repository=repository,
            source=source,
            projection=search_projection,
            dispatcher=dispatcher,
            options=options,
        )
        return service

    monkeypatch.setattr(worker, "WorkerLifecycleService", fake_service)
    repository = object()

    assert worker.configure_lifecycle_repository(repository) is service
    assert captured == {
        "repository": repository,
        "source": storage,
        "projection": projection,
        "dispatcher": worker.dispatch_lifecycle_task,
        "options": {"max_source_bytes": worker.settings.max_ingestion_source_bytes},
    }


def test_duplicate_delivery_is_skipped_after_claim() -> None:
    repository = MemoryRepository(make_job())
    service, _ = make_service(repository, MemoryProjection())
    service.ingest(TASK_ID)

    duplicate = service.ingest(TASK_ID)

    assert duplicate.status == "SKIPPED"
