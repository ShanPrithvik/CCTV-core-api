import os

from celery import Celery


def create_celery(app):
    """
    Create and configure the Celery instance using the new Celery configuration format.
    """
    celery = Celery(
        app.import_name,
        broker=app.config['broker_url'],
        backend=app.config['result_backend']
    )
    
    celery.config_from_object(app.config)

    return celery


def get_redis_url() -> str:
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")
