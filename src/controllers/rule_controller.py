from flask import Blueprint, request, jsonify
from src.services.rule_service import save_rule_for_camera, get_rule_for_camera, remove_camera_rule
import traceback

rule_bp = Blueprint("rule_bp", __name__)

@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["POST"])
def save_rule(camera_id):
  
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        new_rule_config = save_rule_for_camera(camera_id, data)

        return jsonify(new_rule_config), 201
    
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Internal Server Error: {str(e)}")
        traceback.print_exc()
        return jsonify({"error": "Internal server error"}), 500
    

@rule_bp.route("/api/camera/<int:camera_id>/rule", methods=["GET"])
def get_rules(camera_id: str):

    try:
        new_rule_config = get_rule_for_camera(camera_id)
        return jsonify(new_rule_config)

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        print(f"Internal Server Error: {str(e)}")
        traceback.print_exc() 
        return jsonify({"error": "Internal server error"}), 500
    
@rule_bp.route('/api/camera/<int:camera_id>/rule/<int:rule_id>', methods=['DELETE'])
def delete_rule(camera_id, rule_id):
    return remove_camera_rule(camera_id, rule_id)