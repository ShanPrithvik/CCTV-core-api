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
from src.services.stream_utils import display_frame, setup_window, teardown_windows

LOGGER.setLevel("ERROR")

_model = None


def get_model():
    """Lazily load the model so a missing weight file only fails this task,
    instead of crashing the whole Celery worker on import."""
    global _model
    if _model is None:
        model_path = os.getenv("RESTRICTED_MODEL_PATH", "yolov8n.pt")
        _model = YOLO(model_path)
    return _model


DETECTION_FRAME_SKIP = max(1, int(os.getenv("DETECTION_FRAME_SKIP", "3")))


@celery.task(bind=True, base=AbortableTask, name="tasks.process_restricted_area")
def restricted_area_async(self, rtsp_url, camera_id, roi):
    print("===== Celery Task Started for Restricted Area Detection =====")
    print(f"Starting restricted area detection for {rtsp_url}")
    log_file_path = "logs/restricted_area_alerts.txt"
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    cap = None

    try:
        model = get_model()

        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            raise RuntimeError(f"Error: Unable to open video stream from {rtsp_url}")
        # Try to keep internal buffering minimal to reduce latency
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
         
        # Create a display window (no-op when running headless on a server)
        setup_window("Restricted Area Monitoring")

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
        frame_count = 0
        output_folder = os.getenv("SAVED_CLIPS_DIR", "saved_clips")
        os.makedirs(output_folder, exist_ok=True)

        while True:
            # Check if the task has been aborted
            if self.is_aborted():
                print("Task aborted: Restricted area monitoring stopped.")
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

            # Run YOLO detection every Nth frame to keep up on CPU
            if frame_count % DETECTION_FRAME_SKIP == 0:
                results = model(frame)

                # Process detection results
                for result in results:
                    for box in result.boxes:
                        rx1, ry1, rx2, ry2 = map(int, box.xyxy[0])
                        label = model.names[int(box.cls[0])]

                        # Check if the object is inside the ROI
                        center_x = (rx1 + rx2) // 2
                        center_y = (ry1 + ry2) // 2

                        if mask[center_y, center_x] > 0:
                            # Draw bounding box and log alert
                            cv2.rectangle(frame, (rx1, ry1), (rx2, ry2), (0, 255, 0), 2)
                            cv2.putText(frame, f"ALERT: {label} in restricted area", (rx1, ry1 - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                            message = f"{time.strftime('%Y-%m-%d %H:%M:%S')} - ALERT: {label} detected in restricted area for Camera {camera_id}"
                            print(message)
                            with open(log_file_path, "a") as f:
                                f.write(message + "\n")
                            # Start recording with pre-roll if not already recording
                            if not recording:
                                recording = True
                                frames_to_save = list(video_queue)
                                save_start_frame_count = frame_count


            # Handle recording post-roll and asynchronous save
            if recording:
                frames_to_save.append(frame)
                if frame_count - save_start_frame_count >= AFTER_BUFFER_SIZE:
                    recording = False
                    filename = os.path.join(output_folder, f"restricted_area_{camera_id}_{int(time.time())}.mp4")
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

            # Show window (desktop) or publish frame for live streaming (headless)
            if display_frame("Restricted Area Monitoring", frame, camera_id=camera_id):
                print("User quit with 'q'.")
                break

    except Exception as e:
        print(f"Error in restricted area monitoring: {e}")
        
    finally:
        if cap is not None:  # Only release cap if it was initialized
            cap.release()
        teardown_windows()
        print("Stopped restricted area monitoring.")
