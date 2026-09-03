import os

from flask import Flask
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

from src.auth import register_api_key_auth

db = SQLAlchemy()
ma = Marshmallow()
migrate = Migrate()

def create_app():
    app = Flask(__name__)

    app.config.from_object("src.config.db_config.DBConfig")

    # Cap request body size to reject oversized/abusive payloads. Rule/camera
    # JSON is tiny; 1 MiB is generous. Override via MAX_CONTENT_LENGTH_BYTES.
    app.config["MAX_CONTENT_LENGTH"] = int(
        os.getenv("MAX_CONTENT_LENGTH_BYTES", str(1 * 1024 * 1024))
    )

    # CORS_ALLOWED_ORIGINS="*" (default, dev-friendly) or a comma-separated
    # list of allowed origins for production, e.g. "https://myapp.vercel.app"
    allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    origins = "*" if allowed_origins == "*" else [o.strip() for o in allowed_origins.split(",")]
    CORS(
        app,
        resources={r"/*": {"origins": origins}},
        allow_headers=["Content-Type", "Authorization", "X-API-Key"],
        expose_headers=["Content-Type"],
    )

    db.init_app(app)
    ma.init_app(app)
    # Alembic/Flask-Migrate: schema changes go through `flask db migrate` /
    # `flask db upgrade`. create_all() below remains as a first-boot convenience
    # for the SQLite demo so `python app.py` still works with no extra commands.
    migrate.init_app(app, db)

    register_api_key_auth(app)

    @app.after_request
    def set_security_headers(response):
        # Baseline hardening headers. Cheap, safe defaults that do not affect
        # the JSON API or the MJPEG stream.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        return response

    with app.app_context():
        from src.models import Camera, RuleConfig, RuleTypes, User, Organization, Membership  # noqa: F401
        # First-boot convenience for the SQLite demo. Disable when generating
        # or applying Alembic migrations (AUTO_CREATE_TABLES=false) so
        # `flask db migrate` can see the real schema delta.
        auto_create = os.getenv("AUTO_CREATE_TABLES", "true").strip().lower() in (
            "1", "true", "yes",
        )
        if auto_create:
            db.create_all()

    from src.routes import init_routes
    init_routes(app)

    return app
