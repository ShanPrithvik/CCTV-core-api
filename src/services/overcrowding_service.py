import cv2
import time
import os
import numpy as np
from ultralytics import YOLO
from ultralytics.utils import LOGGER
from src.celery_worker import celery
from celery.contrib.abortable import AbortableTask
import collections
from src.services.local_storage import save_video_clip_async
from src.services.event_service import record_detection_event
from src.services.stream_security import mask_credentials
from src.services.stream_utils import (
    display_frame,
    setup_window,
    teardown_windows,
    alert_beep,
)

LOGGER.setLevel("ERROR")

_model = None


def get_model():
    """Lazily load the person-detection model so a missing weight file only
    fails this task, instead of crashing the whole Celery worker on import."""
    global _model
    if _model is None:
        model_path = os.getenv("CROWD_MODEL_PATH", "yolov8n.pt")
        _model = YOLO(model_path)
    return _model


DETECTION_FRAME_SKIP = max(1, int(os.getenv("DETECTION_FRAME_SKIP", "3")))


@celery.task(bind=True, base=AbortableTask, name="tasks.process_detect_overcrowding")
def overcrowd_area_async(self, rtsp_url, camera_id, roi, rule_types):
    print("===== Celery Task Started for Overcrowding Detection =====")
    print(f"Starting detect overcrowding for {mask_credentials(rtsp_url)}")
    log_file_path = "logs/overcrowding_alerts.txt"
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    cap = None

    try:
        model = get_model()

        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            raise RuntimeError("Error: Unable to open video stream")
        # Try to minimize internal buffering if backend supports
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Setup display window (no-op when running headless on a server)
        setup_window("Overcrowding Monitoring")

        # Determine stream properties and prepare pre/post-roll buffers
        FRAME_RATE = int(cap.get(cv2.CAP_PROP_FPS) or 0)
        if FRAME_RATE <= 0 or FRAME_RATE > 120:
            FRAME_RATE = 25  # sensible default when FPS is unknown
        FRAME_WIDTH = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1280)
        FRAME_HEIGHT = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 720)

        # Create a mask for the ROI using actual capture dimensions
        mask = np.zeros((FRAME_HEIGHT, FRAME_WIDTH), dtype=np.uint8)
        pts = np.array([[ (point["x"], point["y"]) for point in roi ]], dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)

        BUFFER_SIZE = FRAME_RATE * 2  # 2 seconds pre-roll
        AFTER_BUFFER_SIZE = FRAME_RATE * 2  # 2 seconds post-roll
        video_queue = collections.deque(maxlen=BUFFER_SIZE)
        recording = False
        frames_to_save = []
        save_start_frame_count = 0
        pending_clip_path = None
        frame_count = 0
        output_folder = os.getenv("SAVED_CLIPS_DIR", "saved_clips")
        os.makedirs(output_folder, exist_ok=True)

        # Extract rule types values
        rule_values = {rule_type.get('type'): rule_type.get('value') for rule_type in rule_types}
        max_people_raw = rule_values.get("Number of Person")
        alert_threshold_raw = rule_values.get("Time to Lookout")
        if max_people_raw is None:
            raise ValueError("Number of Person value is required for CROWD_DETECTION")
        if alert_threshold_raw is None:
            raise ValueError("Time to Lookout value is required for CROWD_DETECTION")
        max_people = int(max_people_raw)
        alert_threshold = int(alert_threshold_raw)

        # Variables for tracking overcrowding
        alert_timer = None
        alert_active = False
        person_count = 0  # cached across skipped frames

        while True:

            # Check if the task has been aborted
            if self.is_aborted():
                print("Task aborted: Overcrowding detection stopped.")
                break

            ret, frame = cap.read()
            if not ret:
                print("End of video or unable to read frame.")
                break

            frame = cv2.resize(frame, (1280, 720))

            # Update counters and ring buffer
            frame_count += 1
            video_queue.append(frame)

            # Draw the ROI polygon on the frame
            cv2.polylines(frame, [pts], isClosed=True, color=(0, 0, 255), thickness=2)

            # Run YOLO detection every Nth frame to keep up on CPU; reuse the
            # last known count on skipped frames.
            if frame_count % DETECTION_FRAME_SKIP == 0:
                results = model(frame)

                person_count = 0
                for result in results:
                    for box in result.boxes:
                        rx1, ry1, rx2, ry2 = map(int, box.xyxy[0])
                        label = model.names[int(box.cls[0])]

                        if label == "person":
                            center_x = (rx1 + rx2) // 2
                            center_y = (ry1 + ry2) // 2

                            if 0 <= center_y < mask.shape[0] and 0 <= center_x < mask.shape[1] and mask[center_y, center_x] > 0:
                                person_count += 1

                                cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
                                cv2.putText(frame, label, (rx1, ry1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)


            if person_count > max_people:
                if alert_timer is None:
                    alert_timer = time.time()

                    message = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Timer Started: Overcrowding detected in Camera {camera_id}"
                    print(message)
                    with open(log_file_path, "a") as f:
                        f.write(message + "\n")

                elif (time.time() - alert_timer >= alert_threshold) and not alert_active:
                    alert_active = True
                    message = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ALERT: Overcrowding detected in Camera {camera_id} for {alert_threshold} seconds!"
                    print(message)
                    with open(log_file_path, "a") as f:
                        f.write(message + "\n")
                    if not recording:
                        recording = True
                        frames_to_save = list(video_queue)
                        save_start_frame_count = frame_count
                        pending_clip_path = os.path.join(
                            output_folder,
                            f"overcrowding_{camera_id}_{int(time.time())}.mp4",
                        )
                        record_detection_event(
                            camera_id=camera_id,
                            event_type="overcrowding_detected",
                            severity="MEDIUM",
                            clip_path=pending_clip_path,
                            metadata={
                                "source": "crowd_detection",
                                "person_count": person_count,
                                "max_people": max_people,
                                "lookout_seconds": alert_threshold,
                            },
                        )

            else:
                if alert_timer is not None:
                    message = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - Timer Reset: Camera {camera_id} has less than {max_people + 1} people."
                    print(message)
                    with open(log_file_path, "a") as f:
                        f.write(message + "\n")
                    alert_timer = None
                    alert_active = False

            # Handle recording post-roll and asynchronous save
            if recording:
                frames_to_save.append(frame)
                if frame_count - save_start_frame_count >= AFTER_BUFFER_SIZE:
                    recording = False
                    filename = pending_clip_path or os.path.join(
                        output_folder, f"overcrowding_{camera_id}_{int(time.time())}.mp4"
                    )
                    save_video_clip_async(
                        frames=frames_to_save,
                        fps=FRAME_RATE,
                        frame_size=(1280, 720),
                        output_path=filename,
                        use_ffmpeg=True,
                        container="mp4",
                        preset="veryfast",
                        gop=FRAME_RATE
                    )
                    print(f"Saving asynchronously: {filename}")
                    frames_to_save.clear()
                    pending_clip_path = None

        # Blinking alert overlay (outside the logic above)
            if alert_active:
                current_time = time.time()
                if int(current_time) % 2 == 0:  # Blink every 2 seconds
                    alert_text = "ALERT: Overcrowding Detected!"
                    font, font_scale, thickness = cv2.FONT_HERSHEY_SIMPLEX, 1.0, 3
                    (text_w, _), _ = cv2.getTextSize(alert_text, font, font_scale, thickness)
                    # Centered near the top, clear of the top-left corner where
                    # the frontend overlays its "LIVE" badge on top of the feed.
                    x = max((frame.shape[1] - text_w) // 2, 0)
                    cv2.putText(frame, alert_text, (x, 110), font, font_scale, (255, 0, 0), thickness)
                    alert_beep(1000, 1000)


            # Show window (desktop) or publish frame for live streaming (headless)
            if display_frame("Overcrowding Monitoring", frame, camera_id=camera_id):
                print("User quit with 'q'.")
                break

    except Exception as e:
        print(f"Error in overcrowding detection: {e}")

    finally:
        if cap is not None:  # Only release cap if it was initialized
            cap.release()
        teardown_windows()
        print("Stopped overcrowding detection.")
