import os

from dotenv import load_dotenv

load_dotenv()

from src.init import create_app

app = create_app()

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app.config.update(
    broker_url=REDIS_URL,
    result_backend=REDIS_URL,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True
)

if __name__ == '__main__':
    # For local development only. In production, run with gunicorn instead:
    #   gunicorn -w 2 -b 0.0.0.0:5000 app:app
    debug = os.getenv("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes")
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "5000"))
    # threaded=True is required: the MJPEG live-view endpoint holds a
    # connection open indefinitely, which would otherwise block every other
    # request (camera list, rules, etc.) on Werkzeug's single-threaded dev
    # server for as long as any Live View tab is open.
    app.run(debug=debug, host=host, port=port, threaded=True)
