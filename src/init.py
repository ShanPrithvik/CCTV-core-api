from flask import Flask
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_marshmallow import Marshmallow

db = SQLAlchemy()
ma = Marshmallow()

def create_app():
    app = Flask(__name__)

    app.config.from_object("src.config.db_config.DBConfig")
    
    # Enable CORS (allow all origins or specify as needed)
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    db.init_app(app)
    ma.init_app(app)

    with app.app_context():
        from src.models import Camera, RuleConfig, RuleTypes
        db.create_all()

    from src.routes import init_routes
    init_routes(app)

    return app
