from celery import Celery

from app.core.config import get_settings

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
    """Minimal contract task used to prove that the worker can consume jobs."""
    return "pong"
