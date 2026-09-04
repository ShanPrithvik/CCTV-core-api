import os
import uuid
import logging

from flask import Flask, g, jsonify, request
from flask_cors import CORS
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow
from werkzeug.exceptions import HTTPException

from src.auth import register_api_key_auth
from src.config.db_config import build_database_uri, sqlalchemy_engine_options

db = SQLAlchemy()
ma = Marshmallow()
migrate = Migrate()
logger = logging.getLogger("cctv")


def create_app():
    app = Flask(__name__)

    app.config.from_object("src.config.db_config.DBConfig")
    app.config["SQLALCHEMY_DATABASE_URI"] = build_database_uri()
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = sqlalchemy_engine_options()

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

    @app.before_request
    def assign_request_id():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex

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
        request_id = getattr(g, "request_id", None)
        if request_id:
            response.headers.setdefault("X-Request-ID", request_id)
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description or exc.name}), exc.code
        logger.exception("Unhandled error rid=%s", getattr(g, "request_id", "-"))
        return jsonify({"error": "Internal server error"}), 500

    with app.app_context():
        from src.models import (  # noqa: F401
            Alert,
            Camera,
            CameraHealth,
            Event,
            Membership,
            Organization,
            RuleConfig,
            RuleTypes,
            User,
        )
        # First-boot convenience for the SQLite demo. Disable when generating
        # or applying Alembic migrations (AUTO_CREATE_TABLES=false) so
        # `flask db migrate` can see the real schema delta.
        auto_create = os.getenv("AUTO_CREATE_TABLES", "true").strip().lower() in (
            "1", "true", "yes",
        )
        if auto_create:
            db.create_all()

        # A rule's detection task runs until the rule is disabled, so restarting
        # the worker leaves rows claiming 'Active' with nothing behind them.
        # Skipped unless a worker actually answers, so booting the API before
        # the worker cannot mass-deactivate rules.
        reconcile_on_startup = os.getenv(
            "RECONCILE_RULES_ON_STARTUP", "true"
        ).strip().lower() in ("1", "true", "yes")
        if reconcile_on_startup:
            from src.services.rule_reconciliation import reconcile_rule_tasks

            result = reconcile_rule_tasks()
            if result["deactivated"]:
                logger.warning(
                    "Deactivated %s rule(s) with no running detection task",
                    result["deactivated"],
                )

    @app.cli.command("reconcile-rules")
    def reconcile_rules_command():
        """Deactivate rules whose Celery detection task is no longer running."""
        from src.services.rule_reconciliation import reconcile_rule_tasks

        result = reconcile_rule_tasks()
        if result["skipped"]:
            print("Skipped: no Celery worker responded.")
        else:
            print(f"Deactivated {result['deactivated']} stale rule(s).")

    from src.routes import init_routes
    init_routes(app)

    return app
