from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.application.tasks import TaskStage as PersistedTaskStage
from app.application.tasks import TaskStatus, can_claim, can_retry, cancellation_target
from app.etl.lifecycle import LifecycleJob, TaskOperation, TaskStage
from app.etl.merchant_reviews import MerchantReviewImportResult
from app.etl.models import ChunkRecord, DocumentRecord, JsonValue
from app.infrastructure.db.base import utc_now
from app.infrastructure.db.models.knowledge import Chunk, Document, DocumentVersion, KnowledgeBase
from app.infrastructure.db.models.tasks import AsyncTask
from app.infrastructure.db.repositories.merchant_import import (
    SQLAlchemyMerchantReviewImporter,
)


class SQLAlchemyLifecycleRepository:
    """Synchronous worker repository backed by MySQL row locks and task leases."""

    def __init__(self, session_factory: sessionmaker[Session], *, lease_seconds: int = 60) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._session_factory = session_factory
        self._merchant_importer = SQLAlchemyMerchantReviewImporter(session_factory)
        self._lease_seconds = lease_seconds
        self._claimed_by: dict[UUID, str] = {}

    def claim(
        self, task_id: UUID, operation: TaskOperation, *, worker_id: str
    ) -> LifecycleJob | None:
        worker_id = worker_id.strip()
        if not worker_id:
            raise ValueError("worker_id must not be blank")
        now = utc_now()
        with self._session_factory.begin() as session:
            task = session.scalar(
                select(AsyncTask).where(AsyncTask.id == task_id).with_for_update()
            )
            if (
                task is None
                or task.task_type != operation.value
                or not can_claim(
                    status=TaskStatus(task.status),
                    attempt_count=task.attempt_count,
                    max_attempts=task.max_attempts,
                    locked_until=task.locked_until,
                    now=now,
                )
            ):
                return None
            claimed_resource = session.execute(
                select(Document, KnowledgeBase)
                .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
                .where(Document.id == task.resource_id)
            ).one_or_none()
            if claimed_resource is None:
                return None
            document, knowledge_base = claimed_resource
            version = session.scalar(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version_no == document.current_version_no,
                )
            )
            if version is None:
                return None

            task.status = TaskStatus.RUNNING.value
            task.attempt_count += 1
            task.locked_by = worker_id
            task.locked_until = now + timedelta(seconds=self._lease_seconds)
            task.heartbeat_at = now
            task.error_code = None
            task.error_message = None
            self._claimed_by[task.id] = task.locked_by
            return LifecycleJob(
                task_id=task.id,
                operation=operation,
                tenant_id=knowledge_base.tenant_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                document_version_id=version.id,
                source_uri=version.file_uri,
                source_key=document.source_key,
                source_sha256=version.file_sha256,
                source_size_bytes=version.file_size,
                mime_type=document.mime_type,
                cleaning_steps=tuple(version.cleaning_config_json.get("steps", ())),
                text_template=_optional_string(version.cleaning_config_json.get("text_template")),
                import_mode=_optional_string(version.cleaning_config_json.get("import_mode")),
                splitter_config=dict(version.splitter_config_json),
            )

    def update_progress(self, task_id: UUID, stage: TaskStage, progress: int) -> None:
        if not 0 <= progress <= 100:
            raise ValueError("progress must be between 0 and 100")
        now = utc_now()
        with self._session_factory.begin() as session:
            task = self._owned_running_task(session, task_id, now)
            if task is None:
                return
            task.stage = stage.value
            task.progress = progress
            task.heartbeat_at = now
            task.locked_until = now + timedelta(seconds=self._lease_seconds)

    def cancellation_requested(self, task_id: UUID) -> bool:
        now = utc_now()
        with self._session_factory() as session:
            task = session.get(AsyncTask, task_id)
            return bool(
                task is not None
                and task.status == TaskStatus.CANCEL_REQUESTED.value
                and task.locked_by == self._claimed_by.get(task_id)
                and task.locked_until is not None
                and task.locked_until > now
            )

    def request_cancel(self, task_id: UUID) -> bool:
        with self._session_factory.begin() as session:
            task = session.scalar(
                select(AsyncTask).where(AsyncTask.id == task_id).with_for_update()
            )
            if task is None:
                return False
            target = cancellation_target(TaskStatus(task.status), PersistedTaskStage(task.stage))
            if target is None:
                return False
            task.status = target.value
            if target is TaskStatus.CANCELLED:
                _release(task)
            return True

    def prepare_retry(self, task_id: UUID) -> TaskOperation | None:
        with self._session_factory.begin() as session:
            task = session.scalar(
                select(AsyncTask).where(AsyncTask.id == task_id).with_for_update()
            )
            if task is None or not can_retry(
                TaskStatus(task.status), task.attempt_count, task.max_attempts
            ):
                return None
            try:
                operation = TaskOperation(task.task_type)
            except ValueError:
                return None
            task.status = TaskStatus.PENDING.value
            task.stage = PersistedTaskStage.QUEUED.value
            task.error_code = None
            task.error_message = None
            _release(task)
            return operation

    def replace_chunks(self, document_version_id: UUID, chunks: Sequence[ChunkRecord]) -> None:
        with self._session_factory.begin() as session:
            embedding_model_id = session.scalar(
                select(KnowledgeBase.embedding_model_version_id)
                .join(Document, Document.knowledge_base_id == KnowledgeBase.id)
                .join(DocumentVersion, DocumentVersion.document_id == Document.id)
                .where(DocumentVersion.id == document_version_id)
            )
            if embedding_model_id is None:
                raise ValueError("document version has no knowledge base embedding model")
            session.execute(delete(Chunk).where(Chunk.document_version_id == document_version_id))
            session.add_all(
                [
                    Chunk(
                        document_version_id=document_version_id,
                        chunk_no=chunk.chunk_no,
                        content=chunk.content,
                        content_hash=chunk.content_hash,
                        token_count=chunk.token_count,
                        page_number=chunk.page_number,
                        metadata_json=dict(chunk.metadata),
                        embedding_model_version_id=embedding_model_id,
                        opensearch_document_id=f"{document_version_id}:{chunk.chunk_no}",
                    )
                    for chunk in chunks
                ]
            )

    def chunks_for_version(self, document_version_id: UUID) -> Sequence[ChunkRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(Chunk)
                .where(
                    Chunk.document_version_id == document_version_id,
                    Chunk.index_status != "DELETED",
                )
                .order_by(Chunk.chunk_no)
            ).all()
            return [
                ChunkRecord(
                    document_version_id=row.document_version_id,
                    chunk_no=row.chunk_no,
                    content=row.content,
                    content_hash=row.content_hash,
                    token_count=row.token_count,
                    page_number=row.page_number,
                    metadata={**dict(row.metadata_json), "chunk_id": str(row.id)},
                )
                for row in rows
            ]

    def mark_chunks_indexed(self, document_version_id: UUID, projection_ids: Sequence[str]) -> None:
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(Chunk)
                .where(Chunk.document_version_id == document_version_id)
                .order_by(Chunk.chunk_no)
                .with_for_update()
            ).all()
            if len(rows) != len(projection_ids):
                raise ValueError("projection id count does not match persisted chunks")
            now = utc_now()
            for row, projection_id in zip(rows, projection_ids, strict=True):
                row.opensearch_document_id = projection_id
                row.index_status = "INDEXED"
                row.indexed_at = now

    def mark_chunks_deleted(self, document_version_id: UUID) -> None:
        with self._session_factory.begin() as session:
            rows = session.scalars(
                select(Chunk)
                .where(Chunk.document_version_id == document_version_id)
                .with_for_update()
            ).all()
            for row in rows:
                row.index_status = "DELETED"

    def mark_document_ready(
        self, document_id: UUID, document_version_id: UUID, chunk_count: int
    ) -> None:
        del chunk_count
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            version = session.get(DocumentVersion, document_version_id)
            if document is None or version is None or version.document_id != document.id:
                raise ValueError("document version does not belong to document")
            document.status = "READY"
            document.current_version_no = version.version_no
            document.last_error_code = None

    def mark_document_failed(self, document_id: UUID, error_code: str) -> None:
        with self._session_factory.begin() as session:
            document = session.get(Document, document_id)
            if document is not None:
                document.status = "FAILED"
                document.last_error_code = error_code

    def import_merchant_reviews(
        self, tenant_id: UUID, records: tuple[DocumentRecord, ...]
    ) -> MerchantReviewImportResult:
        return self._merchant_importer.import_records(tenant_id, records)

    def complete_task(self, task_id: UUID, result: Mapping[str, JsonValue]) -> None:
        with self._session_factory.begin() as session:
            task = self._owned_running_task(session, task_id, utc_now())
            if task is None:
                return
            task.status = TaskStatus.SUCCEEDED.value
            task.progress = 100
            task.result_json = dict(result)
            _release(task)
            self._claimed_by.pop(task_id, None)

    def fail_task(self, task_id: UUID, error_code: str, error_message: str) -> None:
        with self._session_factory.begin() as session:
            task = self._owned_running_task(session, task_id, utc_now())
            if task is None:
                return
            task.status = TaskStatus.FAILED.value
            task.error_code = error_code
            task.error_message = error_message
            _release(task)
            self._claimed_by.pop(task_id, None)

    def cancel_task(self, task_id: UUID) -> None:
        with self._session_factory.begin() as session:
            task = session.scalar(
                select(AsyncTask).where(AsyncTask.id == task_id).with_for_update()
            )
            if (
                task is not None
                and task.status in {TaskStatus.RUNNING.value, TaskStatus.CANCEL_REQUESTED.value}
                and task.locked_by == self._claimed_by.get(task_id)
                and task.locked_until is not None
                and task.locked_until > utc_now()
            ):
                task.status = TaskStatus.CANCELLED.value
                _release(task)
                self._claimed_by.pop(task_id, None)

    def _owned_running_task(
        self, session: Session, task_id: UUID, now: datetime
    ) -> AsyncTask | None:
        task = session.scalar(select(AsyncTask).where(AsyncTask.id == task_id).with_for_update())
        if (
            task is None
            or task.status != TaskStatus.RUNNING.value
            or task.locked_by != self._claimed_by.get(task_id)
            or task.locked_until is None
            or task.locked_until <= now
        ):
            return None
        return task


def _release(task: AsyncTask) -> None:
    task.locked_by = None
    task.locked_until = None
    task.heartbeat_at = None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None
