from flask import Blueprint, jsonify, g
from src.services.rule_service import save_rule_for_camera, get_rule_for_camera, remove_camera_rule
from src.services.org_permissions import is_org_admin, is_org_member, camera_visible_in_org, require_active_org
from src.auth import jwt_required
from src.utils.request_helpers import json_body
import logging

rule_bp = Blueprint("rule_bp", __name__)
logger = logging.getLogger("cctv.rule")


def _get_camera_or_404(camera_id):
    from src.models.camera import Camera
    return Camera.query.filter_by(id=camera_id).first()


def _deny():
    return jsonify({"error": "Forbidden"}), 403


def _authorize_camera(camera_id, admin: bool):
    denied = require_active_org()
    if denied:
        return None, denied

    camera = _get_camera_or_404(camera_id)
    if not camera:
        return None, (jsonify({"error": "Camera not found"}), 404)

    org_id = g.current_org_id
    if not camera_visible_in_org(camera, org_id):
        return None, (jsonify({"error": "Camera not found"}), 404)

    allowed = is_org_admin(org_id) if admin else is_org_member(org_id)
    if not allowed:
        return None, _deny()
    return camera, None


@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["POST"])
@jwt_required
def save_rule(camera_id):
    _, err = _authorize_camera(camera_id, admin=True)
    if err:
        return err

    data = json_body()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        new_rule_config = save_rule_for_camera(
            camera_id, data, organization_id=g.current_org_id
        )
        return jsonify(new_rule_config), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("Failed to save rule")
        return jsonify({"error": "Internal server error"}), 500


@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["GET"])
@jwt_required
def get_rules(camera_id: int):
    _, err = _authorize_camera(camera_id, admin=False)
    if err:
        return err

    try:
        new_rule_config = get_rule_for_camera(camera_id, organization_id=g.current_org_id)
        return jsonify(new_rule_config)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("Failed to fetch rules")
        return jsonify({"error": "Internal server error"}), 500


@rule_bp.route("/api/camera/<int:camera_id>/rule/<int:rule_id>", methods=["PUT"])
@jwt_required
def update_rule(camera_id, rule_id):
    _, err = _authorize_camera(camera_id, admin=True)
    if err:
        return err

    data = json_body()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    try:
        updated_rule = save_rule_for_camera(
            camera_id, data, organization_id=g.current_org_id, existing_rule_id=rule_id
        )
        return jsonify(updated_rule), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        logger.exception("Failed to update rule")
        return jsonify({"error": "Internal server error"}), 500


@rule_bp.route("/api/camera/<int:camera_id>/rule/<int:rule_id>", methods=["DELETE"])
@jwt_required
def delete_rule(camera_id, rule_id):
    _, err = _authorize_camera(camera_id, admin=True)
    if err:
        return err

    payload, status = remove_camera_rule(camera_id, rule_id)
    return jsonify(payload), status
