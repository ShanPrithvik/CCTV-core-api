from sqlalchemy.orm import joinedload

from src.models.camera import Camera
from src.models.ruleConfig import db, RuleConfig
from src.models.ruleTypes import RuleTypes
from src.services.overcrowding_service import overcrowd_area_async
from src.services.shoplifting_service import detect_shoplifting_async
from src.services.restricted_area_service import restricted_area_async
from src.enum.model_types import ModelType
import traceback
import json


def _abort_task(rule_config):
    if not rule_config.task_id:
        return
    try:
        if rule_config.model_type == ModelType.CROWD_DETECTION.value:
            result = overcrowd_area_async.AsyncResult(rule_config.task_id)
        elif rule_config.model_type == ModelType.SHOPLIFTING.value:
            result = detect_shoplifting_async.AsyncResult(rule_config.task_id)
        elif rule_config.model_type == ModelType.RESTRICTED_AREA.value:
            result = restricted_area_async.AsyncResult(rule_config.task_id)
        else:
            return
        result.abort()
    except Exception as e:
        print(f"Error aborting Celery task: {str(e)}")
        traceback.print_exc()


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

    # --- Validate everything before touching the database ---
    dispatch_roi = None
    dispatch_rule_types = []

    if model_type_enum == ModelType.CROWD_DETECTION:
        if not rules:
            raise ValueError("At least one rule is required for CROWD_DETECTION")
        for rule in rules:
            roi = rule.get('roi')
            rule_types = rule.get('ruleTypes', [])

            if not roi or len(roi) != 4:
                raise ValueError("ROI must have exactly 4 points")
            if not all(isinstance(point, dict) and 'x' in point and 'y' in point for point in roi):
                raise ValueError("ROI must be an array of objects with 'x' and 'y' properties")

            dispatch_roi = roi

            for rule_type in rule_types:
                type_name = rule_type.get('type')
                value = rule_type.get('value')
                if type_name is None or value is None:
                    raise ValueError("Rule type and value are required")
                dispatch_rule_types.append({"type": type_name, "value": value})

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

            if not roi or len(roi) != 4:
                raise ValueError("ROI must have exactly 4 points")
            if not all(isinstance(point, dict) and 'x' in point and 'y' in point for point in roi):
                raise ValueError("ROI must be an array of objects with 'x' and 'y' properties")
            if rule_types:
                raise ValueError("RuleTypes must be empty for RESTRICTED AREA model type")

            dispatch_roi = roi

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
        if model_type_enum == ModelType.CROWD_DETECTION:
            task = overcrowd_area_async.delay(camera.rtsp_url, camera_id, dispatch_roi, dispatch_rule_types)
        elif model_type_enum == ModelType.SHOPLIFTING:
            task = detect_shoplifting_async.delay(camera.rtsp_url, camera_id)
        elif model_type_enum == ModelType.RESTRICTED_AREA:
            task = restricted_area_async.delay(camera.rtsp_url, camera_id, dispatch_roi)
        else:
            task = None

        if task is not None:
            rule_config.task_id = task.id
            db.session.commit()
    except RuntimeError as e:
        print(f"Error triggering detection task: {str(e)}")
        traceback.print_exc()
        raise ValueError(f"Failed to start detection: {str(e)}")
    except Exception as e:
        print(f"Error triggering detection task: {str(e)}")
        traceback.print_exc()

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
     
    query = RuleConfig.query.options(joinedload(RuleConfig.rule_types)).filter_by(camera_id=camera_id, status='Active')
    if organization_id is not None:
        query = query.filter_by(organization_id=organization_id)
    rules = query.all()

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
            return ({"error": "Camera not found"})

        rule = RuleConfig.query.filter_by(id=rule_id, camera_id=camera_id).first()
        if not rule:
            return ({"error": "Rule not found for the specified camera"})

        _abort_task(rule)

        rule.status = 'Inactive'
        db.session.commit()

        return ({
            "message": "Rule deleted successfully",
            "name": rule.name,
            "cameraId": camera_id,
            "ruleId": rule_id,
            "status": "Inactive"
        })

    except Exception as e:
        print(f"Error deleting rule: {str(e)}")
        db.session.rollback()
        return ({"error": "An error occurred while deleting the rule"})
