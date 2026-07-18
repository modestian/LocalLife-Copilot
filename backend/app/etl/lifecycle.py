"""Worker-facing orchestration for the knowledge document lifecycle.

Persistence remains behind ports because the knowledge/document/task repositories are
owned by ST-102. This module owns the ETL and search-projection workflow only.
"""

import hashlib
import mimetypes
import re
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from socket import gethostname
from tempfile import SpooledTemporaryFile
from typing import BinaryIO, Protocol
from uuid import UUID

from app.etl.cleaner import (
    CleaningConfigError,
    CleaningFunctionRegistry,
    CleaningReport,
    ConfigurableCleaner,
    RowTemplateError,
)
from app.etl.embeddings import EmbeddingError
from app.etl.loaders import FileLoadError, loader_for
from app.etl.models import ChunkRecord, JsonValue, Metadata
from app.etl.splitters import (
    RecursiveSplitter,
    SemanticSplitter,
    SplitQualityReport,
    SplitterConfigError,
)

DEFAULT_MAX_SOURCE_BYTES = 20 * 1024 * 1024
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class TaskOperation(StrEnum):
    INGEST = "INGEST"
    DELETE = "DELETE"
    REBUILD = "REBUILD"


class TaskStage(StrEnum):
    LOADING = "LOADING"
    CLEANING = "CLEANING"
    SPLITTING = "SPLITTING"
    PERSISTING = "PERSISTING"
    INDEXING = "INDEXING"
    VERIFYING = "VERIFYING"
    DELETING = "DELETING"


class LifecycleError(RuntimeError):
    """Stable worker failure that can be persisted without leaking internals."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectionCountMismatch(LifecycleError):
    def __init__(self, *, expected: int, actual: int) -> None:
        super().__init__(
            "PROJECTION_COUNT_MISMATCH",
            f"expected {expected} indexed chunks but found {actual}",
        )


class SourceFileTooLarge(LifecycleError):
    def __init__(self, *, maximum: int) -> None:
        super().__init__(
            "FILE_TOO_LARGE",
            f"source exceeds the maximum allowed size of {maximum} bytes",
        )


class _CancellationRequested(Exception):
    pass


@dataclass(frozen=True, slots=True)
class LifecycleJob:
    """Immutable snapshot loaded when an async task is claimed."""

    task_id: UUID
    operation: TaskOperation
    tenant_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    document_version_id: UUID
    source_uri: str | None = None
    source_key: str | None = None
    source_sha256: str | None = None
    source_size_bytes: int | None = None
    mime_type: str | None = None
    metadata: Metadata = field(default_factory=dict)
    cleaning_steps: tuple[Mapping[str, object], ...] = ()
    text_template: str | None = None
    max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES
    splitter_config: Mapping[str, JsonValue] = field(
        default_factory=lambda: {
            "strategy": "recursive",
            "chunk_size": 500,
            "chunk_overlap": 80,
        }
    )


@dataclass(frozen=True, slots=True)
class WorkerTaskResult:
    task_id: UUID
    operation: TaskOperation
    status: str
    details: Mapping[str, JsonValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JsonValue]:
        return {
            "task_id": str(self.task_id),
            "operation": self.operation.value,
            "status": self.status,
            "details": dict(self.details),
        }


class SourceStorage(Protocol):
    def open(self, uri: str) -> AbstractContextManager[BinaryIO]: ...


class SearchProjection(Protocol):
    """Idempotent OpenSearch projection operations."""

    def upsert(self, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None: ...

    def delete(self, document_version_id: UUID) -> int: ...

    def count(self, document_version_id: UUID) -> int: ...


class LifecycleRepository(Protocol):
    """Port implemented by the ST-102 task/document repositories."""

    def claim(
        self, task_id: UUID, operation: TaskOperation, *, worker_id: str
    ) -> LifecycleJob | None: ...

    def update_progress(self, task_id: UUID, stage: TaskStage, progress: int) -> None: ...

    def cancellation_requested(self, task_id: UUID) -> bool: ...

    def request_cancel(self, task_id: UUID) -> bool: ...

    def prepare_retry(self, task_id: UUID) -> TaskOperation | None: ...

    def replace_chunks(self, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None: ...

    def chunks_for_version(self, document_version_id: UUID) -> Sequence[ChunkRecord]: ...

    def mark_chunks_indexed(
        self, document_version_id: UUID, projection_ids: Sequence[str]
    ) -> None: ...

    def mark_chunks_deleted(self, document_version_id: UUID) -> None: ...

    def mark_document_ready(
        self, document_id: UUID, document_version_id: UUID, chunk_count: int
    ) -> None: ...

    def mark_document_failed(self, document_id: UUID, error_code: str) -> None: ...

    def complete_task(self, task_id: UUID, result: Mapping[str, JsonValue]) -> None: ...

    def fail_task(self, task_id: UUID, error_code: str, error_message: str) -> None: ...

    def cancel_task(self, task_id: UUID) -> None: ...


class TaskDispatcher(Protocol):
    def __call__(self, operation: TaskOperation, task_id: UUID) -> None: ...


def projection_id(document_version_id: UUID, chunk_no: int) -> str:
    """Return the deterministic OpenSearch ID required by the design contract."""
    return f"{document_version_id}:{chunk_no}"


class WorkerLifecycleService:
    """Coordinate claim, progress, cancellation and final lifecycle state."""

    def __init__(
        self,
        repository: LifecycleRepository,
        storage: SourceStorage,
        projection: SearchProjection,
        dispatcher: TaskDispatcher,
        *,
        cleaning_functions: CleaningFunctionRegistry | None = None,
        worker_id: str | None = None,
        max_source_bytes: int = DEFAULT_MAX_SOURCE_BYTES,
    ) -> None:
        if max_source_bytes <= 0:
            raise ValueError("max_source_bytes must be greater than zero")
        self._repository = repository
        self._storage = storage
        self._projection = projection
        self._dispatcher = dispatcher
        self._cleaning_functions = cleaning_functions or CleaningFunctionRegistry()
        self._worker_id = worker_id or gethostname()
        self._max_source_bytes = max_source_bytes

    def ingest(self, task_id: UUID) -> WorkerTaskResult:
        return self._execute(task_id, TaskOperation.INGEST, self._ingest)

    def delete(self, task_id: UUID) -> WorkerTaskResult:
        return self._execute(task_id, TaskOperation.DELETE, self._delete)

    def rebuild(self, task_id: UUID) -> WorkerTaskResult:
        return self._execute(task_id, TaskOperation.REBUILD, self._rebuild)

    def retry(self, task_id: UUID) -> WorkerTaskResult:
        operation = self._repository.prepare_retry(task_id)
        if operation is None:
            return WorkerTaskResult(task_id, TaskOperation.INGEST, "SKIPPED")
        self._dispatcher(operation, task_id)
        return WorkerTaskResult(task_id, operation, "PENDING")

    def cancel(self, task_id: UUID) -> bool:
        """Persist a cancellation request; workers observe it at safe checkpoints."""
        return self._repository.request_cancel(task_id)

    def _execute(
        self,
        task_id: UUID,
        operation: TaskOperation,
        handler: Callable[[LifecycleJob], Mapping[str, JsonValue]],
    ) -> WorkerTaskResult:
        job = self._repository.claim(task_id, operation, worker_id=self._worker_id)
        if job is None:
            return WorkerTaskResult(task_id, operation, "SKIPPED")
        try:
            details = handler(job)
        except _CancellationRequested:
            self._repository.cancel_task(task_id)
            return WorkerTaskResult(task_id, operation, "CANCELLED")
        except Exception as exc:
            code = self._error_code(exc)
            self._repository.fail_task(task_id, code, str(exc))
            if operation is not TaskOperation.DELETE:
                self._repository.mark_document_failed(job.document_id, code)
            raise
        self._repository.complete_task(task_id, details)
        return WorkerTaskResult(task_id, operation, "SUCCEEDED", details)

    @staticmethod
    def _error_code(exc: Exception) -> str:
        if isinstance(exc, LifecycleError):
            return exc.code
        if isinstance(exc, FileLoadError):
            return "FILE_LOAD_FAILED"
        if isinstance(exc, CleaningConfigError | RowTemplateError):
            return "CLEANING_FAILED"
        if isinstance(exc, SplitterConfigError):
            return "SPLITTING_FAILED"
        if isinstance(exc, EmbeddingError):
            return exc.code
        return "WORKER_PROCESSING_FAILED"

    def _checkpoint(self, job: LifecycleJob, stage: TaskStage, progress: int) -> None:
        if self._repository.cancellation_requested(job.task_id):
            raise _CancellationRequested
        self._repository.update_progress(job.task_id, stage, progress)

    def _ingest(self, job: LifecycleJob) -> Mapping[str, JsonValue]:
        if not job.source_uri or not job.source_key:
            raise LifecycleError(
                "INVALID_INGEST_JOB", "ingestion requires source_uri and source_key"
            )

        self._checkpoint(job, TaskStage.LOADING, 5)
        source_metadata = dict(job.metadata)
        # Security-sensitive projection fields always come from the claimed database
        # relationships, never from caller-controlled source metadata.
        source_metadata["tenant_id"] = str(job.tenant_id)
        source_metadata["knowledge_base_id"] = str(job.knowledge_base_id)
        source_metadata["document_id"] = str(job.document_id)
        source_metadata["document_version_id"] = str(job.document_version_id)
        source_metadata["resource_scope"] = [f"KNOWLEDGE_BASE:{job.knowledge_base_id}"]
        with self._storage.open(job.source_uri) as source:
            validated_source, source_report = self._validate_source(
                source,
                source_key=job.source_key,
                expected_hash=job.source_sha256,
                expected_size=job.source_size_bytes,
                expected_mime=job.mime_type,
                maximum=min(job.max_source_bytes, self._max_source_bytes),
            )
            with validated_source:
                records = list(
                    loader_for(job.source_key).load(
                        validated_source,
                        source_key=job.source_key,
                        metadata=source_metadata,
                    )
                )

        self._checkpoint(job, TaskStage.CLEANING, 25)
        cleaner = ConfigurableCleaner(
            job.cleaning_steps,
            text_template=job.text_template,
            custom_functions=self._cleaning_functions,
        )
        cleaned = cleaner.clean(records)
        cleaning_report = cleaner.last_report

        self._checkpoint(job, TaskStage.SPLITTING, 45)
        splitter = self._splitter(job.splitter_config)
        chunks = splitter.split(cleaned, document_version_id=job.document_version_id)
        splitting_report = splitter.last_report
        if not chunks:
            raise LifecycleError("NO_INDEXABLE_CHUNKS", "ingestion produced no indexable chunks")

        # PERSISTING and later stages are deliberately treated as non-interruptible.
        self._checkpoint(job, TaskStage.PERSISTING, 65)
        self._repository.replace_chunks(job.document_version_id, chunks)
        result = dict(self._index_and_finalize(job, chunks))
        result["source_validation"] = source_report
        result["cleaning_report"] = self._cleaning_report_json(cleaning_report)
        result["splitting_report"] = self._splitting_report_json(splitting_report)
        return result

    def _rebuild(self, job: LifecycleJob) -> Mapping[str, JsonValue]:
        self._checkpoint(job, TaskStage.PERSISTING, 35)
        chunks = list(self._repository.chunks_for_version(job.document_version_id))
        if not chunks:
            raise LifecycleError("NO_STORED_CHUNKS", "rebuild requires existing stored chunks")
        self._projection.delete(job.document_version_id)
        return self._index_and_finalize(job, chunks)

    def _delete(self, job: LifecycleJob) -> Mapping[str, JsonValue]:
        # The command side must make the document invisible before dispatching this task.
        self._repository.update_progress(job.task_id, TaskStage.DELETING, 50)
        deleted = self._projection.delete(job.document_version_id)
        self._repository.mark_chunks_deleted(job.document_version_id)
        return {"deleted_projection_count": deleted}

    def _index_and_finalize(
        self, job: LifecycleJob, chunks: Sequence[ChunkRecord]
    ) -> Mapping[str, JsonValue]:
        self._repository.update_progress(job.task_id, TaskStage.INDEXING, 80)
        self._projection.upsert(job.document_version_id, chunks)
        self._repository.update_progress(job.task_id, TaskStage.VERIFYING, 95)
        actual = self._projection.count(job.document_version_id)
        if actual != len(chunks):
            raise ProjectionCountMismatch(expected=len(chunks), actual=actual)
        ids = [projection_id(job.document_version_id, chunk.chunk_no) for chunk in chunks]
        self._repository.mark_chunks_indexed(job.document_version_id, ids)
        self._repository.mark_document_ready(job.document_id, job.document_version_id, actual)
        return {"document_version_id": str(job.document_version_id), "chunk_count": actual}

    @staticmethod
    def _splitter(config: Mapping[str, JsonValue]) -> RecursiveSplitter | SemanticSplitter:
        values = dict(config)
        strategy = values.pop("strategy", "recursive")
        try:
            if strategy == "recursive":
                return RecursiveSplitter(**values)  # type: ignore[arg-type]
            if strategy == "semantic":
                return SemanticSplitter(**values)  # type: ignore[arg-type]
        except (TypeError, SplitterConfigError) as exc:
            raise LifecycleError("INVALID_SPLITTER_CONFIG", str(exc)) from exc
        raise LifecycleError("INVALID_SPLITTER_CONFIG", f"unsupported strategy: {strategy}")

    @staticmethod
    def _validate_source(
        source: BinaryIO,
        *,
        source_key: str,
        expected_hash: str | None,
        expected_size: int | None,
        expected_mime: str | None,
        maximum: int,
    ) -> tuple[BinaryIO, dict[str, JsonValue]]:
        if maximum <= 0:
            raise LifecycleError("INVALID_INGEST_JOB", "max_source_bytes must be greater than zero")
        if expected_hash is not None and _SHA256_PATTERN.fullmatch(expected_hash) is None:
            raise LifecycleError(
                "INVALID_INGEST_JOB", "source_sha256 must be a lowercase SHA-256 digest"
            )
        if expected_size is not None and expected_size < 0:
            raise LifecycleError(
                "INVALID_INGEST_JOB", "source_size_bytes must be greater than or equal to zero"
            )
        if expected_size is not None and expected_size > maximum:
            raise SourceFileTooLarge(maximum=maximum)

        stream = SpooledTemporaryFile(max_size=min(maximum, 8 * 1024 * 1024), mode="w+b")
        digest = hashlib.sha256()
        size = 0
        try:
            source.seek(0)
            while payload := source.read(64 * 1024):
                size += len(payload)
                if size > maximum:
                    raise SourceFileTooLarge(maximum=maximum)
                digest.update(payload)
                stream.write(payload)
            actual_hash = digest.hexdigest()
            if expected_size is not None and size != expected_size:
                raise LifecycleError(
                    "FILE_SIZE_MISMATCH",
                    f"expected source size {expected_size} bytes but read {size} bytes",
                )
            if expected_hash is not None and actual_hash != expected_hash:
                raise LifecycleError("FILE_HASH_MISMATCH", "source SHA-256 does not match metadata")
            detected_mime = mimetypes.guess_type(source_key)[0]
            if expected_mime is not None and detected_mime != expected_mime:
                raise LifecycleError(
                    "FILE_MIME_MISMATCH",
                    f"source MIME {expected_mime!r} does not match {detected_mime!r}",
                )
            stream.seek(0)
            return stream, {
                "size_bytes": size,
                "sha256": actual_hash,
                "mime_type": detected_mime,
            }
        except LifecycleError:
            stream.close()
            raise
        except (OSError, ValueError) as exc:
            stream.close()
            raise FileLoadError("source stream could not be read") from exc

    @staticmethod
    def _cleaning_report_json(report: CleaningReport | None) -> dict[str, JsonValue]:
        if report is None:
            return {}
        return {
            "input_count": report.input_count,
            "output_count": report.output_count,
            "steps": [
                {
                    "step_type": step.step_type,
                    "input_count": step.input_count,
                    "output_count": step.output_count,
                    "duration_ms": step.duration_ms,
                    "error_samples": list(step.error_samples),
                }
                for step in report.steps
            ],
        }

    @staticmethod
    def _splitting_report_json(report: SplitQualityReport | None) -> dict[str, JsonValue]:
        if report is None:
            return {}
        return {
            "strategy": report.strategy,
            "input_records": report.input_records,
            "skipped_records": report.skipped_records,
            "chunk_count": report.chunk_count,
            "duplicate_chunks": report.duplicate_chunks,
            "total_characters": report.total_characters,
            "total_tokens": report.total_tokens,
            "min_chunk_characters": report.min_chunk_characters,
            "max_chunk_characters": report.max_chunk_characters,
            "average_chunk_characters": report.average_chunk_characters,
            "duration_ms": report.duration_ms,
            "parameters": report.parameters,
        }
