from flask import Blueprint
from src.controllers.camera_controller import add_camera, get_cameras, remove_camera
from src.controllers.rule_controller import save_rule

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
def home():
    return "CCTV Surveillance System"

def init_routes(app):
    from src.controllers.camera_controller import camera_bp
    from src.controllers.rule_controller import rule_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(camera_bp)
    app.register_blueprint(rule_bp)