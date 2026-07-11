from src.init import create_app
from src.config.celery_config import create_celery

app = create_app()

app.config.update(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/0",
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True
)

if __name__ == '__main__':
    app.run(debug=True, port = 5000)

