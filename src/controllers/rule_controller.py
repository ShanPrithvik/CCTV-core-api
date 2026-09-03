from flask import Blueprint, request, jsonify, g
from src.services.rule_service import save_rule_for_camera, get_rule_for_camera, remove_camera_rule
from src.services.org_permissions import is_org_admin, is_org_member
from src.auth import jwt_required
import traceback

rule_bp = Blueprint("rule_bp", __name__)


def _get_camera_or_404(camera_id):
    from src.models.camera import Camera
    camera = Camera.query.filter_by(id=camera_id).first()
    if not camera:
        return None
    return camera


def _camera_org_matches(camera, org_id) -> bool:
    # Legacy cameras (organization_id is NULL) are not org-scoped.
    return camera.organization_id is None or org_id is None or camera.organization_id == org_id


def _deny():
    return jsonify({"error": "Forbidden"}), 403


@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["POST"])
@jwt_required
def save_rule(camera_id):
    try:
        camera = _get_camera_or_404(camera_id)
        if not camera:
            return jsonify({"error": "Camera not found"}), 404

        org_id = g.current_org_id
        if not _camera_org_matches(camera, org_id) or not is_org_admin(camera.organization_id or org_id):
            return _deny()

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        new_rule_config = save_rule_for_camera(camera_id, data, organization_id=org_id)

        return jsonify(new_rule_config), 201
      
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Internal Server Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500
      

@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["GET"])
@jwt_required
def get_rules(camera_id: str):
    try:
        camera = _get_camera_or_404(camera_id)
        if not camera:
            return jsonify({"error": "Camera not found"}), 404

        org_id = g.current_org_id
        if not _camera_org_matches(camera, org_id) or not is_org_member(camera.organization_id or org_id):
            return _deny()

        new_rule_config = get_rule_for_camera(camera_id, organization_id=org_id)
        return jsonify(new_rule_config)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Internal Server Error: {str(e)}")
        traceback.print_exc() 
        return jsonify({"error": "Internal server error"}), 500
      

@rule_bp.route('/api/camera/<int:camera_id>/rule/<int:rule_id>', methods=['PUT'])
@jwt_required
def update_rule(camera_id, rule_id):
    try:
        camera = _get_camera_or_404(camera_id)
        if not camera:
            return jsonify({"error": "Camera not found"}), 404

        org_id = g.current_org_id
        if not _camera_org_matches(camera, org_id) or not is_org_admin(camera.organization_id or org_id):
            return _deny()

        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        updated_rule = save_rule_for_camera(camera_id, data, organization_id=org_id, existing_rule_id=rule_id)

        return jsonify(updated_rule), 200

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Internal Server Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500


@rule_bp.route('/api/camera/<int:camera_id>/rule/<int:rule_id>', methods=['DELETE'])
@jwt_required
def delete_rule(camera_id, rule_id):
    camera = _get_camera_or_404(camera_id)
    if not camera:
        return jsonify({"error": "Camera not found"}), 404

    org_id = g.current_org_id
    if not _camera_org_matches(camera, org_id) or not is_org_admin(camera.organization_id or org_id):
        return _deny()

    return remove_camera_rule(camera_id, rule_id)
