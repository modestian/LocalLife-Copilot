from celery import Celery
from celery.signals import worker_process_init

from app.core.config import get_settings
from app.review_analysis import get_classifier

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


@worker_process_init.connect
def preload_model(sender, **kwargs):
    get_classifier()


@celery_app.task(name="system.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="review_analysis.classify")
def classify_reviews(texts: list[str]) -> list[dict]:
    classifier = get_classifier()
    result = classifier.classify_batch(texts)
    return [item.model_dump() for item in result.results]


@celery_app.task(name="review_analysis.classify_single")
def classify_single_review(text: str) -> dict:
    classifier = get_classifier()
    result = classifier.classify(text)
    return result.model_dump()
