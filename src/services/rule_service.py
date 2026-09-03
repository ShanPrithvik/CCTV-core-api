from sqlalchemy.orm import joinedload

from src.models.camera import Camera
from src.models.ruleConfig import db, RuleConfig
from src.models.ruleTypes import RuleTypes
from src.enum.model_types import ModelType
from src.utils.validation import parse_positive_int
import logging
import math

logger = logging.getLogger("cctv.rule")


def _detection_task(model_type_value):
    """Import Celery tasks lazily so API tests/CI do not load YOLO/torch."""
    if model_type_value == ModelType.CROWD_DETECTION.value:
        from src.services.overcrowding_service import overcrowd_area_async
        return overcrowd_area_async
    if model_type_value == ModelType.SHOPLIFTING.value:
        from src.services.shoplifting_service import detect_shoplifting_async
        return detect_shoplifting_async
    if model_type_value == ModelType.RESTRICTED_AREA.value:
        from src.services.restricted_area_service import restricted_area_async
        return restricted_area_async
    return None

logger = logging.getLogger("cctv.rule")


def _validated_roi(roi):
    if not roi or len(roi) != 4:
        raise ValueError("ROI must have exactly 4 points")
    points = []
    for point in roi:
        if not isinstance(point, dict) or "x" not in point or "y" not in point:
            raise ValueError("ROI must be an array of objects with 'x' and 'y' properties")
        try:
            x = float(point["x"])
            y = float(point["y"])
        except (TypeError, ValueError):
            raise ValueError("ROI coordinates must be numbers")
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("ROI coordinates must be finite numbers")
        if not (0 <= x <= 10000 and 0 <= y <= 10000):
            raise ValueError("ROI coordinates are out of range")
        points.append({"x": x, "y": y})
    return points



def _abort_task(rule_config):
    if not rule_config.task_id:
        return
    try:
        task = _detection_task(rule_config.model_type)
        if task is None:
            return
        task.AsyncResult(rule_config.task_id).abort()
    except Exception:
        logger.exception("Error aborting Celery task")


def save_rule_for_camera(camera_id, data, organization_id=None, existing_rule_id=None):
    """
    Handle the logic of saving a rule configuration for a camera.
    If existing_rule_id is provided, update that rule instead of creating a new one.
    """
    name = data.get('name')
    model_type = data.get('modelType')
    rules = data.get('rule', [])

    if not name:
        raise ValueError("Rule name is required")

    if not model_type:
        raise ValueError("Model type is required")

    try:
        model_type_enum = ModelType[model_type]
    except KeyError:
        raise ValueError(f"Invalid model type: {model_type}")

    camera = Camera.query.filter_by(id=camera_id).first()
    if not camera:
        raise ValueError("Camera not found")
    if organization_id is not None and camera.organization_id != organization_id:
        raise ValueError("Camera not found")

    # --- Validate everything before touching the database ---
    dispatch_roi = None
    dispatch_rule_types = []

    if model_type_enum == ModelType.CROWD_DETECTION:
        if not rules:
            raise ValueError("At least one rule is required for CROWD_DETECTION")
        for rule in rules:
            roi = rule.get('roi')
            rule_types = rule.get('ruleTypes', [])

            dispatch_roi = _validated_roi(roi)

            for rule_type in rule_types:
                type_name = rule_type.get('type')
                value = rule_type.get('value')
                if type_name is None or value is None:
                    raise ValueError("Rule type and value are required")
                dispatch_rule_types.append({"type": type_name, "value": value})

        type_names = {rt["type"] for rt in dispatch_rule_types}
        if "Number of Person" not in type_names or "Time to Lookout" not in type_names:
            raise ValueError("CROWD_DETECTION requires 'Number of Person' and 'Time to Lookout'")
        parse_positive_int(
            next(rt["value"] for rt in dispatch_rule_types if rt["type"] == "Number of Person"),
            "Number of Person",
        )
        parse_positive_int(
            next(rt["value"] for rt in dispatch_rule_types if rt["type"] == "Time to Lookout"),
            "Time to Lookout",
        )

    elif model_type_enum == ModelType.SHOPLIFTING:
        for rule in rules:
            roi = rule.get('roi', [])
            rule_types = rule.get('ruleTypes', [])
            if roi:
                raise ValueError("ROI must be empty for SHOPLIFTING model type")
            if rule_types:
                raise ValueError("RuleTypes must be empty for SHOPLIFTING model type")

    elif model_type_enum == ModelType.RESTRICTED_AREA:
        if not rules:
            raise ValueError("At least one rule is required for RESTRICTED_AREA")
        for rule in rules:
            roi = rule.get('roi')
            rule_types = rule.get('ruleTypes', [])

            if rule_types:
                raise ValueError("RuleTypes must be empty for RESTRICTED AREA model type")

            dispatch_roi = _validated_roi(roi)

    # --- Apply changes ---
    if existing_rule_id:
        rule_config = RuleConfig.query.filter_by(id=existing_rule_id, camera_id=camera_id).first()
        if not rule_config:
            raise ValueError("Rule not found")
        rule_config.name = name
        rule_config.model_type = model_type_enum.value
        rule_config.organization_id = organization_id
        _abort_task(rule_config)
        rule_config.task_id = None
        RuleTypes.query.filter_by(ruleconfig_id=rule_config.id).delete()
    else:
        rule_config = RuleConfig(
            camera_id=camera_id,
            model_type=model_type_enum.value,
            roi_coordinates=[],
            name=name,
            organization_id=organization_id,
        )
        db.session.add(rule_config)
        db.session.flush()

    if model_type_enum != ModelType.SHOPLIFTING:
        rule_config.roi_coordinates = dispatch_roi

    for rule_type in dispatch_rule_types:
        db.session.add(RuleTypes(
            ruleconfig_id=rule_config.id,
            rule_type=rule_type["type"],
            rule_value=rule_type["value"],
        ))

    db.session.commit()

    # --- Dispatch the detection task ---
    try:
        task_fn = _detection_task(model_type_enum.value)
        if task_fn is None:
            task = None
        elif model_type_enum == ModelType.CROWD_DETECTION:
            task = task_fn.delay(camera.rtsp_url, camera_id, dispatch_roi, dispatch_rule_types)
        elif model_type_enum == ModelType.SHOPLIFTING:
            task = task_fn.delay(camera.rtsp_url, camera_id)
        else:
            task = task_fn.delay(camera.rtsp_url, camera_id, dispatch_roi)

        if task is not None:
            rule_config.task_id = task.id
            db.session.commit()
    except RuntimeError:
        logger.exception("Error triggering detection task")
        raise ValueError("Failed to start detection")
    except Exception:
        logger.exception("Error triggering detection task")

    response = {
        "cameraId": rule_config.camera_id,
        "id": rule_config.id,
        "modelType": rule_config.model_type,
        "name": rule_config.name,
        "roi": str(rule_config.roi_coordinates)
    }

    return response

def get_rule_for_camera(camera_id: str, organization_id=None):

    camera = Camera.query.filter_by(id=camera_id).first()
    if not camera:
        raise ValueError("Camera not found")
    if organization_id is None or camera.organization_id != organization_id:
        raise ValueError("Camera not found")

    rules = (
        RuleConfig.query.options(joinedload(RuleConfig.rule_types))
        .filter_by(camera_id=camera_id, status="Active", organization_id=organization_id)
        .all()
    )

    if not rules:
        return ({"camera_id": camera_id, "rules": []})

    rules_data = []
    for rule in rules:
        rule_types_data = [{"type": rt.rule_type, "value": rt.rule_value} for rt in rule.rule_types]

        rule_temp = {
            "roi": rule.roi_coordinates,
            "ruleTypes": rule_types_data
        }
        rule_data = {
            "id": rule.id,
            "name": rule.name,
            "modelType": rule.model_type,
            "rule": [rule_temp]
        }
        rules_data.append(rule_data)

    response = {
        "camera_id": camera_id,
        "rules": rules_data
    }

    return response


def remove_camera_rule(camera_id, rule_id):
    """
    Delete a rule for a specific camera by setting its status to 'inactive'.
    """
    try:
        camera = Camera.query.filter_by(id=camera_id).first()
        if not camera:
            return {"error": "Camera not found"}, 404

        rule = RuleConfig.query.filter_by(id=rule_id, camera_id=camera_id).first()
        if not rule:
            return {"error": "Rule not found for the specified camera"}, 404

        _abort_task(rule)

        rule.status = "Inactive"
        db.session.commit()

        return {
            "message": "Rule deleted successfully",
            "name": rule.name,
            "cameraId": camera_id,
            "ruleId": rule_id,
            "status": "Inactive",
        }, 200

    except Exception:
        logger.exception("Error deleting rule")
        db.session.rollback()
        return {"error": "An error occurred while deleting the rule"}, 500
