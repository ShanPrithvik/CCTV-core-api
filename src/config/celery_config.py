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
