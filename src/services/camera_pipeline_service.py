"""One decode loop per camera, every active rule drawn on the same frame."""
import collections
import os
import time

import cv2
from celery.contrib.abortable import AbortableTask

from src.celery_worker import celery
from src.enum.model_types import ModelType
from src.services.event_service import record_detection_event, worker_app
from src.services.local_storage import save_video_clip_async
from src.services.overlay import (
    PROCESS_SIZE,
    build_roi_mask,
    draw_alert_banners,
    draw_box,
    draw_roi,
    draw_rule_legend,
    point_in_mask,
    style_for,
)
from src.services.stream_security import mask_credentials
from src.services.stream_utils import (
    alert_beep,
    display_frame,
    read_rules_epoch,
    setup_window,
    teardown_windows,
)

DETECTION_FRAME_SKIP = max(1, int(os.getenv("DETECTION_FRAME_SKIP", "3")))
SHOPLIFTING_FRAME_SKIP = max(1, int(os.getenv("SHOPLIFTING_FRAME_SKIP", "2")))
RESTRICTED_ALERT_COOLDOWN_SECONDS = max(
    1, int(os.getenv("RESTRICTED_ALERT_COOLDOWN_SECONDS", "60"))
)
RULES_RELOAD_SECONDS = max(1.0, float(os.getenv("PIPELINE_RULE_RELOAD_SECONDS", "2")))

_person_model = None
_shoplifting_model = None


def get_person_model():
    global _person_model
    if _person_model is None:
        from ultralytics import YOLO
        from ultralytics.utils import LOGGER

        LOGGER.setLevel("ERROR")
        _person_model = YOLO(os.getenv("CROWD_MODEL_PATH", "yolov8n.pt"))
    return _person_model


def get_shoplifting_model():
    global _shoplifting_model
    if _shoplifting_model is None:
        from ultralytics import YOLO
        from ultralytics.utils import LOGGER

        LOGGER.setLevel("ERROR")
        path = os.getenv("SHOPLIFTING_MODEL_PATH", "src/trained-models/shoplifting_best.pt")
        _shoplifting_model = YOLO(path)
        _shoplifting_model.conf = 0.7
    return _shoplifting_model


def load_active_rules(camera_id):
    """Snapshot of Active rules for this camera, safe to call from a worker."""
    from sqlalchemy.orm import joinedload

    from src.models.ruleConfig import RuleConfig

    app = worker_app()
    with app.app_context():
        from src.init import db

        db.session.expire_all()
        rows = (
            RuleConfig.query.options(joinedload(RuleConfig.rule_types))
            .filter_by(camera_id=int(camera_id), status="Active")
            .all()
        )
        specs = []
        for row in rows:
            specs.append(
                {
                    "id": row.id,
                    "name": row.name,
                    "model_type": row.model_type,
                    "roi": row.roi_coordinates or [],
                    "rule_types": [
                        {"type": rt.rule_type, "value": rt.rule_value}
                        for rt in row.rule_types
                    ],
                }
            )
        return specs


def _init_runtime(spec, fps: int):
    values = {item.get("type"): item.get("value") for item in spec.get("rule_types") or []}
    mask, pts = (None, None)
    if spec["model_type"] != ModelType.SHOPLIFTING.value:
        mask, pts = build_roi_mask(spec.get("roi") or [])
    max_people = None
    lookout = None
    if spec["model_type"] == ModelType.CROWD_DETECTION.value:
        try:
            max_people = int(values.get("Number of Person"))
            lookout = int(values.get("Time to Lookout"))
        except (TypeError, ValueError):
            max_people, lookout = None, None
    return {
        "spec": spec,
        "mask": mask,
        "pts": pts,
        "max_people": max_people,
        "lookout": lookout,
        "person_count": 0,
        "alert_timer": None,
        "alert_active": False,
        "recording": False,
        "frames_to_save": [],
        "save_start_frame": 0,
        "pending_clip_path": None,
        "last_alert_at": 0.0,
        "last_shop_boxes": [],
    }


def _sync_runtime(specs, states, fps: int):
    keep = {spec["id"] for spec in specs}
    for rule_id in list(states):
        if rule_id not in keep:
            del states[rule_id]
    for spec in specs:
        current = states.get(spec["id"])
        if current is None:
            states[spec["id"]] = _init_runtime(spec, fps)
            continue
        current["spec"] = spec
        if spec["model_type"] != ModelType.SHOPLIFTING.value:
            current["mask"], current["pts"] = build_roi_mask(spec.get("roi") or [])
        if spec["model_type"] == ModelType.CROWD_DETECTION.value:
            values = {item.get("type"): item.get("value") for item in spec.get("rule_types") or []}
            try:
                current["max_people"] = int(values.get("Number of Person"))
                current["lookout"] = int(values.get("Time to Lookout"))
            except (TypeError, ValueError):
                pass


def _person_boxes(results):
    boxes = []
    for result in results:
        names = result.names
        for box in result.boxes:
            label = names[int(box.cls[0])]
            if label != "person":
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            boxes.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "conf": float(box.conf[0]),
                    "cx": (x1 + x2) // 2,
                    "cy": (y1 + y2) // 2,
                }
            )
    return boxes


def _shoplifting_boxes(results):
    boxes = []
    for result in results:
        names = result.names
        for box in result.boxes:
            label = names[int(box.cls[0])]
            conf = float(box.conf[0])
            if label != "Shoplifting" or conf < 0.3:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "conf": conf})
    return boxes


def _finish_clip(state, fps, filename):
    save_video_clip_async(
        frames=state["frames_to_save"],
        fps=fps,
        frame_size=PROCESS_SIZE,
        output_path=filename,
        use_ffmpeg=True,
        container="mp4",
        preset="veryfast",
        gop=fps,
    )
    state["frames_to_save"] = []
    state["pending_clip_path"] = None
    state["recording"] = False


@celery.task(bind=True, base=AbortableTask, name="tasks.process_camera_pipeline")
def process_camera_pipeline(self, rtsp_url, camera_id):
    print(f"===== Camera pipeline started for camera {camera_id} {mask_credentials(rtsp_url)} =====")
    os.makedirs("logs", exist_ok=True)
    output_folder = os.getenv("SAVED_CLIPS_DIR", "saved_clips")
    os.makedirs(output_folder, exist_ok=True)
    cap = None
    person_model = None
    shop_model = None
    states = {}
    last_epoch = None
    last_reload = 0.0

    try:
        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            raise RuntimeError("Error: Unable to open video stream")
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        fps = int(cap.get(cv2.CAP_PROP_FPS) or 0)
        if fps <= 0 or fps > 120:
            fps = 25
        preroll = fps * 2
        postroll = fps * 2
        video_queue = collections.deque(maxlen=preroll)
        frame_count = 0
        setup_window(f"Camera {camera_id}")

        specs = load_active_rules(camera_id)
        _sync_runtime(specs, states, fps)
        last_epoch = read_rules_epoch(camera_id)
        last_reload = time.time()

        needs_person = any(
            s["model_type"] in (ModelType.CROWD_DETECTION.value, ModelType.RESTRICTED_AREA.value)
            for s in specs
        )
        needs_shop = any(s["model_type"] == ModelType.SHOPLIFTING.value for s in specs)
        if needs_person:
            person_model = get_person_model()
        if needs_shop:
            shop_model = get_shoplifting_model()

        last_person_dets = []
        last_shop_dets = []

        while True:
            if self.is_aborted():
                print(f"Camera pipeline aborted for camera {camera_id}")
                break

            now = time.time()
            epoch = read_rules_epoch(camera_id)
            if epoch != last_epoch or now - last_reload >= RULES_RELOAD_SECONDS:
                specs = load_active_rules(camera_id)
                _sync_runtime(specs, states, fps)
                last_epoch = epoch
                last_reload = now
                if not specs:
                    print(f"Camera {camera_id} has no active rules; stopping pipeline")
                    break
                needs_person = any(
                    s["model_type"]
                    in (ModelType.CROWD_DETECTION.value, ModelType.RESTRICTED_AREA.value)
                    for s in specs
                )
                needs_shop = any(s["model_type"] == ModelType.SHOPLIFTING.value for s in specs)
                if needs_person and person_model is None:
                    person_model = get_person_model()
                if needs_shop and shop_model is None:
                    shop_model = get_shoplifting_model()

            ret, frame = cap.read()
            if not ret:
                print("End of video or unable to read frame.")
                break

            frame = cv2.resize(frame, PROCESS_SIZE)
            frame_count += 1
            video_queue.append(frame.copy())

            person_dets = last_person_dets
            shop_dets = last_shop_dets
            if needs_person and person_model is not None and frame_count % DETECTION_FRAME_SKIP == 0:
                last_person_dets = _person_boxes(person_model(frame))
                person_dets = last_person_dets
            if needs_shop and shop_model is not None and frame_count % SHOPLIFTING_FRAME_SKIP == 0:
                last_shop_dets = _shoplifting_boxes(shop_model(frame))
                shop_dets = last_shop_dets

            banners = []
            for spec in specs:
                state = states[spec["id"]]
                style = style_for(spec["model_type"])
                model_type = spec["model_type"]

                if model_type != ModelType.SHOPLIFTING.value:
                    draw_roi(frame, state["pts"], style["bgr"])

                if model_type == ModelType.CROWD_DETECTION.value:
                    if person_dets:
                        state["person_count"] = 0
                        for det in person_dets:
                            if state["mask"] is not None and point_in_mask(
                                state["mask"], det["cx"], det["cy"]
                            ):
                                state["person_count"] += 1
                                draw_box(
                                    frame,
                                    det["x1"],
                                    det["y1"],
                                    det["x2"],
                                    det["y2"],
                                    style["box"],
                                    "person",
                                )
                    max_people = state["max_people"]
                    lookout = state["lookout"]
                    if max_people is None or lookout is None:
                        continue
                    if state["person_count"] > max_people:
                        if state["alert_timer"] is None:
                            state["alert_timer"] = now
                        elif now - state["alert_timer"] >= lookout and not state["alert_active"]:
                            state["alert_active"] = True
                            if not state["recording"]:
                                state["recording"] = True
                                state["frames_to_save"] = list(video_queue)
                                state["save_start_frame"] = frame_count
                                state["pending_clip_path"] = os.path.join(
                                    output_folder,
                                    f"overcrowding_{camera_id}_{int(now)}.mp4",
                                )
                                record_detection_event(
                                    camera_id=camera_id,
                                    event_type="overcrowding_detected",
                                    severity="MEDIUM",
                                    clip_path=state["pending_clip_path"],
                                    metadata={
                                        "source": "crowd_detection",
                                        "person_count": state["person_count"],
                                        "max_people": max_people,
                                        "lookout_seconds": lookout,
                                        "rule_id": spec["id"],
                                    },
                                )
                    else:
                        state["alert_timer"] = None
                        state["alert_active"] = False
                    if state["alert_active"] and int(now) % 2 == 0:
                        banners.append(("ALERT: Overcrowding Detected!", style["bgr"]))
                        alert_beep(1000, 1000)

                elif model_type == ModelType.RESTRICTED_AREA.value:
                    for det in person_dets:
                        if state["mask"] is None or not point_in_mask(
                            state["mask"], det["cx"], det["cy"]
                        ):
                            continue
                        draw_box(
                            frame,
                            det["x1"],
                            det["y1"],
                            det["x2"],
                            det["y2"],
                            style["box"],
                            "RESTRICTED",
                        )
                        cooldown_elapsed = (
                            now - state["last_alert_at"] >= RESTRICTED_ALERT_COOLDOWN_SECONDS
                        )
                        if not state["recording"] and cooldown_elapsed:
                            state["last_alert_at"] = now
                            state["recording"] = True
                            state["frames_to_save"] = list(video_queue)
                            state["save_start_frame"] = frame_count
                            state["pending_clip_path"] = os.path.join(
                                output_folder,
                                f"restricted_area_{camera_id}_{int(now)}.mp4",
                            )
                            record_detection_event(
                                camera_id=camera_id,
                                event_type="person_entered_restricted_zone",
                                severity="HIGH",
                                confidence=det["conf"],
                                clip_path=state["pending_clip_path"],
                                metadata={
                                    "source": "restricted_area",
                                    "label": "person",
                                    "rule_id": spec["id"],
                                },
                            )
                            banners.append(("ALERT: person in restricted area", style["bgr"]))

                elif model_type == ModelType.SHOPLIFTING.value:
                    if shop_dets:
                        state["last_shop_boxes"] = shop_dets
                    for det in state["last_shop_boxes"]:
                        draw_box(
                            frame,
                            det["x1"],
                            det["y1"],
                            det["x2"],
                            det["y2"],
                            style["box"],
                            "SHOPLIFTING",
                        )
                    if shop_dets and not state["recording"]:
                        state["recording"] = True
                        state["frames_to_save"] = list(video_queue)
                        state["save_start_frame"] = frame_count
                        state["pending_clip_path"] = os.path.join(
                            output_folder,
                            f"shoplifting_{camera_id}_{int(now)}.mp4",
                        )
                        record_detection_event(
                            camera_id=camera_id,
                            event_type="shoplifting_detected",
                            severity="HIGH",
                            confidence=shop_dets[0]["conf"],
                            clip_path=state["pending_clip_path"],
                            metadata={"source": "shoplifting", "rule_id": spec["id"]},
                        )
                        banners.append(("ALERT: Shoplifting Detected!", style["bgr"]))

                if state["recording"]:
                    state["frames_to_save"].append(frame.copy())
                    if frame_count - state["save_start_frame"] >= postroll:
                        filename = state["pending_clip_path"] or os.path.join(
                            output_folder, f"clip_{camera_id}_{int(now)}.mp4"
                        )
                        _finish_clip(state, fps, filename)

            draw_rule_legend(frame, specs)
            draw_alert_banners(frame, banners)

            if display_frame(
                f"Camera {camera_id}", frame, camera_id=camera_id, owner=self.request.id
            ):
                break

    except Exception as e:
        print(f"Error in camera pipeline: {e}")
    finally:
        if cap is not None:
            cap.release()
        teardown_windows()
        print(f"Stopped camera pipeline for camera {camera_id}")
