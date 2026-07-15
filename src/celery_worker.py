import os

from celery import Celery
from dotenv import load_dotenv

load_dotenv()


def create_celery():
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    celery = Celery(
        "distributed_cctv",
        broker=redis_url,
        backend=redis_url
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