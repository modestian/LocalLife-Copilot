from io import BytesIO
from uuid import UUID, uuid4

import pytest

from app.etl.lifecycle import LifecycleJob, TaskOperation, WorkerLifecycleService, projection_id
from app.etl.loaders import FileLoadError, loader_for, normalized_content_hash
from app.etl.models import ChunkRecord, CleanStatus

DEFAULT_PAYLOAD = "第一段。第二段。".encode()


@pytest.mark.parametrize(
    "source_key",
    ["sample.pdf", "sample.docx", "sample.md", "sample.txt", "sample.csv", "sample.xlsx"],
)
def test_supported_format_fixtures_produce_canonical_records(
    source_key: str, ingestion_format_payloads: dict[str, bytes]
) -> None:
    records = list(
        loader_for(source_key).load(
            BytesIO(ingestion_format_payloads[source_key]),
            source_key=source_key,
            metadata={"knowledge_base_id": "kb-fixture"},
        )
    )

    assert records
    for record in records:
        assert isinstance(record.content, str)
        assert record.source_key.startswith(source_key)
        assert record.metadata["knowledge_base_id"] == "kb-fixture"
        assert record.metadata["location"] == source_key
        assert record.content_hash == normalized_content_hash(record.content)
        assert record.clean_status is CleanStatus.CLEANED


@pytest.mark.parametrize(
    "source_key",
    [
        "invalid.pdf",
        "invalid.docx",
        "invalid.txt",
        "invalid.md",
        "invalid.csv",
        "invalid.xlsx",
    ],
)
def test_malformed_format_fixtures_return_explicit_load_errors(
    source_key: str, invalid_ingestion_payloads: dict[str, bytes]
) -> None:
    with pytest.raises(FileLoadError, match=r"(could not be parsed|must be UTF-8)"):
        list(
            loader_for(source_key).load(
                BytesIO(invalid_ingestion_payloads[source_key]),
                source_key=source_key,
            )
        )


class MemoryStorage:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def open(self, uri: str) -> BytesIO:
        assert uri == "memory://same-file"
        return BytesIO(self.payload)


class MemoryProjection:
    def __init__(self) -> None:
        self.chunks: dict[UUID, list[ChunkRecord]] = {}

    def upsert(self, document_version_id: UUID, chunks: list[ChunkRecord]) -> None:
        self.chunks[document_version_id] = list(chunks)

    def delete(self, document_version_id: UUID) -> int:
        return len(self.chunks.pop(document_version_id, []))

    def count(self, document_version_id: UUID) -> int:
        return len(self.chunks.get(document_version_id, []))


class MemoryRepository:
    def __init__(self, job: LifecycleJob) -> None:
        self.job = job
        self.claimed = False
        self.chunks: dict[UUID, list[ChunkRecord]] = {}
        self.indexed_ids: list[str] = []
        self.deleted_versions: list[UUID] = []

    def claim(self, task_id, operation, *, worker_id):
        if self.claimed:
            return None
        assert task_id == self.job.task_id
        assert operation == self.job.operation
        self.claimed = True
        return self.job

    def update_progress(self, task_id, stage, progress):
        pass

    def cancellation_requested(self, task_id):
        return False

    def request_cancel(self, task_id):
        return False

    def prepare_retry(self, task_id):
        return None

    def replace_chunks(self, document_version_id, chunks):
        self.chunks[document_version_id] = list(chunks)

    def chunks_for_version(self, document_version_id):
        return self.chunks.get(document_version_id, [])

    def mark_chunks_indexed(self, document_version_id, projection_ids):
        self.indexed_ids = list(projection_ids)

    def mark_chunks_deleted(self, document_version_id):
        self.deleted_versions.append(document_version_id)

    def mark_document_ready(self, document_id, document_version_id, chunk_count):
        pass

    def mark_document_failed(self, document_id, error_code):
        pass

    def complete_task(self, task_id, result):
        pass

    def fail_task(self, task_id, error_code, error_message):
        pass

    def cancel_task(self, task_id):
        pass


def make_job(operation: TaskOperation, version_id: UUID, *, reason: str | None = None):
    return LifecycleJob(
        task_id=uuid4(),
        operation=operation,
        tenant_id=uuid4(),
        knowledge_base_id=uuid4(),
        document_id=uuid4(),
        document_version_id=version_id,
        source_uri="memory://same-file" if operation is TaskOperation.INGEST else None,
        source_key="same-file.txt" if operation is TaskOperation.INGEST else None,
        metadata={"lifecycle_reason": reason} if reason else {},
        splitter_config={"strategy": "recursive", "chunk_size": 100, "chunk_overlap": 0},
    )


def make_service(job, projection, payload=DEFAULT_PAYLOAD):
    repository = MemoryRepository(job)
    service = WorkerLifecycleService(
        repository,
        MemoryStorage(payload),
        projection,
        lambda operation, task_id: None,
        worker_id="worker-test",
    )
    return service, repository


def test_reimporting_same_file_keeps_chunk_projection_idempotent() -> None:
    version_id = uuid4()
    projection = MemoryProjection()

    first_job = make_job(TaskOperation.INGEST, version_id)
    first_service, _ = make_service(first_job, projection)
    first_service.ingest(first_job.task_id)
    first_hashes = [chunk.content_hash for chunk in projection.chunks[version_id]]

    repeated_job = make_job(TaskOperation.INGEST, version_id)
    repeated_service, repository = make_service(repeated_job, projection)
    repeated_service.ingest(repeated_job.task_id)
    repeated_chunks = projection.chunks[version_id]

    assert [chunk.content_hash for chunk in repeated_chunks] == first_hashes
    assert repository.indexed_ids == [
        projection_id(version_id, chunk.chunk_no) for chunk in repeated_chunks
    ]
    assert projection.count(version_id) == len(first_hashes)


@pytest.mark.parametrize("reason", ["DELETED", "CLOSED", "EXPIRED", "INVALID"])
def test_inactive_lifecycle_reasons_remove_online_projection(reason: str) -> None:
    version_id = uuid4()
    projection = MemoryProjection()
    ingest_job = make_job(TaskOperation.INGEST, version_id)
    ingest_service, _ = make_service(ingest_job, projection)
    ingest_service.ingest(ingest_job.task_id)
    assert projection.count(version_id) > 0

    delete_job = make_job(TaskOperation.DELETE, version_id, reason=reason)
    delete_service, repository = make_service(delete_job, projection)
    result = delete_service.delete(delete_job.task_id)

    assert result.status == "SUCCEEDED"
    assert projection.count(version_id) == 0
    assert repository.deleted_versions == [version_id]


def test_repeated_delete_is_idempotent() -> None:
    version_id = uuid4()
    projection = MemoryProjection()
    for expected_count in (0, 0):
        delete_job = make_job(TaskOperation.DELETE, version_id, reason="DELETED")
        delete_service, _ = make_service(delete_job, projection)
        result = delete_service.delete(delete_job.task_id)
        assert result.details["deleted_projection_count"] == expected_count
    assert projection.count(version_id) == 0
