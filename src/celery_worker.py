from celery import Celery
from dotenv import load_dotenv

from src.config.redis_config import get_redis_url

load_dotenv()


def create_celery():
    redis_url = get_redis_url()

    celery = Celery(
        "distributed_cctv",
        broker=redis_url,
        backend=redis_url
    )
    celery.conf.update(
        broker_connection_retry_on_startup=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        worker_prefetch_multiplier=1,
        task_acks_late=True,
    )

    # related_name=None: these entries *are* the task modules to import
    # directly (they are not packages containing a separate "tasks"
    # submodule), so this actually registers the @celery.task functions
    # with the worker process.
    celery.autodiscover_tasks([
        "src.services.shoplifting_service",
        "src.services.overcrowding_service",
        "src.services.restricted_area_service",
    ], related_name=None)

    return celery

celery = create_celery()
