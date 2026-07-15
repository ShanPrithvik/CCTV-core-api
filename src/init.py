import os

from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

db = SQLAlchemy()
ma = Marshmallow()

def create_app():
    app = Flask(__name__)

    app.config.from_object("src.config.db_config.DBConfig")

    # CORS_ALLOWED_ORIGINS="*" (default, dev-friendly) or a comma-separated
    # list of allowed origins for production, e.g. "https://myapp.vercel.app"
    allowed_origins = os.getenv("CORS_ALLOWED_ORIGINS", "*")
    origins = "*" if allowed_origins == "*" else [o.strip() for o in allowed_origins.split(",")]
    CORS(app, resources={r"/api/*": {"origins": origins}})

    db.init_app(app)
    ma.init_app(app)

    with app.app_context():
        from src.models import Camera, RuleConfig, RuleTypes
        db.create_all()

    from src.routes import init_routes
    init_routes(app)

    return app
