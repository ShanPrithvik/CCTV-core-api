from src.models.camera import Camera
from src.models.ruleConfig import db, RuleConfig
from src.models.ruleTypes import RuleTypes
from src.services.overcrowding_service import overcrowd_area_async
from src.services.shoplifting_service import detect_shoplifting_async
from src.services.restricted_area_service import restricted_area_async
from src.enum.model_types import ModelType
import traceback
import json


def save_rule_for_camera(camera_id, data):
    """
    Handle the logic of saving a rule configuration for a camera.
    """
    try:
        name = data.get('name')
        model_type = data.get('modelType')
        rules = data.get('rule', [])

        if not name:
            raise ValueError("Rule name is required")
        
        if not model_type:
            raise ValueError("Model type is required")

        # Validate model_type using the Enum
        try:
            model_type_enum = ModelType[model_type]
        except KeyError:
            raise ValueError(f"Invalid model type: {model_type}")

        # Check if the camera exists
        camera = Camera.query.filter_by(id=camera_id).first()
        if not camera:
            raise ValueError("Camera not found")

        # Create a new RuleConfig
        new_rule_config = RuleConfig(
            camera_id=camera_id,
            model_type=model_type_enum.value,  # Store the string value of the enum
            roi_coordinates=[],  # Initialize with empty ROI
            name=name
        )
        db.session.add(new_rule_config)
        db.session.commit()

        # Save rule details based on the model type
        if model_type_enum == ModelType.CROWD_DETECTION:
            for rule in rules:
                roi = rule.get('roi')
               
                rule_types = rule.get('ruleTypes', [])

                if not roi or len(roi) != 4:
                    raise ValueError("ROI must have exactly 4 points")
                
                if not all(isinstance(point, dict) and 'x' in point and 'y' in point for point in roi):
                    raise ValueError("ROI must be an array of objects with 'x' and 'y' properties")

                new_rule_config.roi_coordinates = roi
                db.session.commit()

                for rule_type in rule_types:
                    type_name = rule_type.get('type')
                    value = rule_type.get('value')

                    if not type_name or not value:
                        raise ValueError("Rule type and value are required")

                    new_rule_type = RuleTypes(
                        ruleconfig_id=new_rule_config.id,
                        rule_type=type_name,
                        rule_value=value
                    )
                    db.session.add(new_rule_type)
                    print(f"Added RuleType: ruleconfig_id={new_rule_config.id}, type={type_name}, value={value}")

                db.session.commit()

            try:
                task =  overcrowd_area_async.delay(camera.rtsp_url, camera_id, roi, rule_types)
                new_rule_config.task_id = task.id
                db.session.commit()
            except Exception as e:
                print(f"Error triggering overcrowding detection: {str(e)}")
                traceback.print_exc()

        elif model_type_enum == ModelType.SHOPLIFTING:
            for rule in rules:
                roi = rule.get('roi', [])
                rule_types = rule.get('ruleTypes', [])

                if roi:
                    raise ValueError("ROI must be empty for SHOPLIFTING model type")
                if rule_types:
                    raise ValueError("RuleTypes must be empty for SHOPLIFTING model type")

                new_rule_config.roi_coordinates = roi
                db.session.commit()

                for rule_type in rule_types:
                    type_name = rule_type.get('type')
                    value = rule_type.get('value')

                    if not type_name or not value:
                        raise ValueError("Rule type and value are required")

                    new_rule_type = RuleTypes(
                        ruleconfig_id=new_rule_config.id,
                        rule_type=type_name,
                        rule_value=value
                    )
                    db.session.add(new_rule_type)
                    print(f"Added RuleType: ruleconfig_id={new_rule_config.id}, type={type_name}, value={value}")

                db.session.commit()

            try:
                task = detect_shoplifting_async.delay(camera.rtsp_url)
                new_rule_config.task_id = task.id
                db.session.commit()
            except Exception as e:
                print(f"Error triggering shoplifting detection: {str(e)}")
                traceback.print_exc()

        elif model_type_enum == ModelType.RESTRICTED_AREA:
            for rule in rules:
                roi = rule.get('roi')

                rule_types = rule.get('ruleTypes', [])

                if not roi or len(roi) != 4:
                    raise ValueError("ROI must have exactly 4 points")
                if not all(isinstance(point, dict) and 'x' in point and 'y' in point for point in roi):
                    raise ValueError("ROI must be an array of objects with 'x' and 'y' properties")
                if rule_types:
                    raise ValueError("RuleTypes must be empty for RESTRICTED AREA model type")

                new_rule_config.roi_coordinates = roi
                db.session.commit()

            try:
                task = restricted_area_async.delay(camera.rtsp_url, camera_id, roi)
                new_rule_config.task_id = task.id
                db.session.commit()
            except RuntimeError as e:
                print(f"Error in restricted_area: {str(e)}")
                raise ValueError(f"Failed to start restricted area monitoring: {str(e)}")

        response = {
            "cameraId": new_rule_config.camera_id,
            "id": new_rule_config.id,
            "modelType": new_rule_config.model_type,
            "name": new_rule_config.name,
            "roi": str(new_rule_config.roi_coordinates)  # Convert ROI to string
        }

        return response

    except Exception as e:
        print(f"Error in save_rule_for_camera: {str(e)}")
        traceback.print_exc()
        raise

def get_rule_for_camera(camera_id: str):

    camera = Camera.query.filter_by(id=camera_id).first()
    if not camera:
        raise ValueError("Camera not found")
     
    rules = RuleConfig.query.filter_by(camera_id=camera_id, status='Active').all()

    if not rules:
        return ({"camera_id": camera_id, "rules": []})

    rules_data = []
    for rule in rules:
        rule_types_config = RuleTypes.query.filter_by(ruleconfig_id=rule.id).all()
        rule_types_data = [{"type": rt.rule_type, "value": rt.rule_value} for rt in rule_types_config]

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

        if rule.task_id:
            try:
                if rule.model_type == ModelType.CROWD_DETECTION.value:
                    result = overcrowd_area_async.AsyncResult(rule.task_id)
                elif rule.model_type == ModelType.SHOPLIFTING.value:
                    result = detect_shoplifting_async.AsyncResult(rule.task_id)
                elif rule.model_type == ModelType.RESTRICTED_AREA.value:
                    result = restricted_area_async.AsyncResult(rule.task_id)

                result.abort()
            except Exception as e:
                print(f"Error aborting Celery task: {str(e)}")
                traceback.print_exc()


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
