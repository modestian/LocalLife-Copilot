from uuid import UUID

from celery import Celery
from opensearchpy import OpenSearch

from app.core.config import get_settings
from app.etl.adapters import LocalSourceStorage, OpenSearchProjection
from app.etl.embeddings import BatchedEmbedder, HttpEmbeddingProvider
from app.etl.lifecycle import LifecycleRepository, TaskOperation, WorkerLifecycleService

settings = get_settings()

celery_app = Celery(
    "local_life_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return _ping_impl()


_lifecycle_service: WorkerLifecycleService | None = None
_lifecycle_projection_client: OpenSearch | None = None


def configure_lifecycle_service(service: WorkerLifecycleService) -> None:
    global _lifecycle_service
    _lifecycle_service = service


def configure_lifecycle_repository(repository: LifecycleRepository) -> WorkerLifecycleService:
    """Build production ETL adapters around the task/document repository."""
    global _lifecycle_projection_client
    _lifecycle_projection_client = OpenSearch(settings.opensearch_url)
    embedding_provider = HttpEmbeddingProvider(
        settings.model_gateway_embedding_url,
        model=settings.embedding_model,
        timeout_seconds=settings.dependency_timeout_seconds,
    )
    embedder = BatchedEmbedder(
        embedding_provider,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
    )
    service = WorkerLifecycleService(
        repository,
        LocalSourceStorage(settings.knowledge_data_root),
        OpenSearchProjection(
            _lifecycle_projection_client,
            settings.opensearch_write_alias,
            embedder,
        ),
        dispatch_lifecycle_task,
        max_source_bytes=settings.max_ingestion_source_bytes,
    )
    configure_lifecycle_service(service)
    return service


def _lifecycle() -> WorkerLifecycleService:
    if _lifecycle_service is None:
        raise RuntimeError("knowledge lifecycle service has not been configured")
    return _lifecycle_service


@celery_app.task(name="knowledge.ingest")
def ingest_document(task_id: str) -> dict[str, object]:
    return _lifecycle().ingest(UUID(task_id)).to_json()


@celery_app.task(name="knowledge.retry")
def retry_document_task(task_id: str) -> dict[str, object]:
    return _lifecycle().retry(UUID(task_id)).to_json()


@celery_app.task(name="knowledge.cancel")
def cancel_document_task(task_id: str) -> dict[str, object]:
    accepted = _lifecycle().cancel(UUID(task_id))
    status = "CANCEL_REQUESTED" if accepted else "REJECTED"
    return {"task_id": task_id, "status": status}


@celery_app.task(name="knowledge.delete")
def delete_document_projection(task_id: str) -> dict[str, object]:
    return _lifecycle().delete(UUID(task_id)).to_json()


@celery_app.task(name="knowledge.rebuild")
def rebuild_document_projection(task_id: str) -> dict[str, object]:
    return _lifecycle().rebuild(UUID(task_id)).to_json()


def dispatch_lifecycle_task(operation: TaskOperation, task_id: UUID) -> None:
    task_names = {
        TaskOperation.INGEST: "knowledge.ingest",
        TaskOperation.DELETE: "knowledge.delete",
        TaskOperation.REBUILD: "knowledge.rebuild",
    }
    celery_app.send_task(task_names[operation], args=[str(task_id)])


def _ping_impl() -> str:
    """Minimal contract task used to prove that the worker can consume jobs."""
    return "pong"
