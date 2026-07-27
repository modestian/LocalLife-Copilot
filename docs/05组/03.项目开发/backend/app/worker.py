import asyncio
from pathlib import Path
from uuid import UUID

from celery import Celery
from opensearchpy import OpenSearch
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.etl.adapters import LocalSourceStorage, OpenSearchProjection
from app.etl.embeddings import BatchedEmbedder, HttpEmbeddingProvider
from app.etl.lifecycle import LifecycleRepository, TaskOperation, WorkerLifecycleService
from app.infrastructure.db.repositories.lifecycle import SQLAlchemyLifecycleRepository
from app.infrastructure.db.repositories.tasks import (
    SQLAlchemyOutboxRepository,
    SQLAlchemyTaskRepository,
)
from app.operations.task_runtime import OperationalTaskRuntime

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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={"visibility_timeout": 3600},
    beat_schedule={
        "publish-outbox-events": {
            "task": "system.publish_outbox",
            "schedule": 5.0,
        },
        "recover-stale-knowledge-tasks": {
            "task": "system.recover_stale_knowledge_tasks",
            "schedule": 30.0,
        },
    },
)


@celery_app.task(name="system.ping")
def ping() -> str:
    return _ping_impl()


@celery_app.task(name="system.publish_outbox")
def publish_outbox() -> dict[str, int]:
    """Drain committed Outbox rows; failed dispatches remain eligible for retry."""
    return asyncio.run(_publish_outbox())


async def _publish_outbox() -> dict[str, int]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    repository = SQLAlchemyOutboxRepository(async_sessionmaker(engine, expire_on_commit=False))
    published = 0
    failed = 0
    publisher_id = "celery-outbox-publisher"
    try:
        claims = await repository.claim_batch(publisher_id=publisher_id, limit=100)
        for claim in claims:
            try:
                task_id = str(claim.payload["task_id"])
                celery_app.send_task(claim.event_type, args=[task_id])
            except Exception as exc:
                failed += 1
                await repository.mark_failed(
                    claim.event_id,
                    publisher_id=publisher_id,
                    error_message=str(exc),
                )
            else:
                if await repository.mark_published(claim.event_id, publisher_id=publisher_id):
                    published += 1
    finally:
        await engine.dispose()
    return {"published": published, "failed": failed}


@celery_app.task(name="system.recover_stale_knowledge_tasks")
def recover_stale_knowledge_tasks() -> dict[str, int]:
    return asyncio.run(_recover_stale_knowledge_tasks())


async def _recover_stale_knowledge_tasks() -> dict[str, int]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    repository = SQLAlchemyTaskRepository(async_sessionmaker(engine, expire_on_commit=False))
    try:
        recovered = await repository.recover_stale_knowledge_tasks()
    finally:
        await engine.dispose()
    return {"recovered": recovered}


_lifecycle_service: WorkerLifecycleService | None = None
_lifecycle_projection_client: OpenSearch | None = None
_lifecycle_engine: Engine | None = None


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
        timeout_seconds=settings.embedding_request_timeout_seconds,
        max_attempts=settings.embedding_request_max_attempts,
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
        _configure_default_lifecycle_service()
    if _lifecycle_service is None:
        raise RuntimeError("knowledge lifecycle service could not be configured")
    return _lifecycle_service


def _configure_default_lifecycle_service() -> None:
    global _lifecycle_engine
    _lifecycle_engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    repository = SQLAlchemyLifecycleRepository(
        sessionmaker(_lifecycle_engine, expire_on_commit=False)
    )
    configure_lifecycle_repository(repository)


async def _run_operational_task(task_id: UUID, method_name: str) -> dict[str, object]:
    # Celery invokes each sync task through a fresh asyncio.run() event loop. An
    # async connection pool therefore cannot be cached safely between tasks.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    runtime = OperationalTaskRuntime(
        async_sessionmaker(engine, expire_on_commit=False),
        artifact_root=Path(settings.training_artifact_root),
        worker_id="celery-operational-worker",
    )
    try:
        method = getattr(runtime, method_name)
        return await method(task_id)
    finally:
        await engine.dispose()


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


@celery_app.task(name="merchant.analysis")
def analyze_merchant(task_id: str) -> dict[str, object]:
    return asyncio.run(_run_operational_task(UUID(task_id), "run_merchant_analysis"))


@celery_app.task(name="fine_tuning.train")
def train_fine_tuning_job(task_id: str) -> dict[str, object]:
    return asyncio.run(_run_operational_task(UUID(task_id), "run_fine_tuning"))


@celery_app.task(name="fine_tuning.evaluate")
def evaluate_fine_tuning_job(task_id: str) -> dict[str, object]:
    return asyncio.run(_run_operational_task(UUID(task_id), "run_evaluation"))


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
