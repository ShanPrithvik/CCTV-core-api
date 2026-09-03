from flask import Blueprint, jsonify
from sqlalchemy import text
from src.controllers.camera_controller import camera_bp
from src.controllers.rule_controller import rule_bp
from src.controllers.auth_controller import auth_bp
from src.controllers.membership_controller import membership_bp
from src.init import db

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    return "CCTV Surveillance System"


@main_bp.route("/healthz")
def healthz():
    """Liveness probe: the process is up and serving requests."""
    return jsonify({"status": "ok"}), 200


@main_bp.route("/readyz")
def readyz():
    """Readiness probe: verify the database is reachable before taking traffic."""
    try:
        db.session.execute(text("SELECT 1"))
        return jsonify({"status": "ready"}), 200
    except Exception as e:
        return jsonify({"status": "not_ready", "error": str(e)}), 503

def init_routes(app):
    app.register_blueprint(main_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(rule_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(membership_bp)
