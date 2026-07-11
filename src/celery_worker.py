from celery import Celery

def create_celery():
    
    celery = Celery(
        "distributed_cctv",
        broker="redis://localhost:6379/0",
        backend="redis://localhost:6379/0"
    )

    # Autodiscover tasks in the 'tasks' module
    celery.autodiscover_tasks([
        "src.services.shoplifting_service", 
        "src.services.overcrowding_service",
        "src.services.restricted_area_service",
    ])

    return celery

celery = create_celery()