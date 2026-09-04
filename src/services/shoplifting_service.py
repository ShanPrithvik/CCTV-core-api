import cv2
import time
from src.celery_worker import celery
import collections
import os
from ultralytics import YOLO
from ultralytics.utils import LOGGER
from celery.contrib.abortable import AbortableTask
from src.services.local_storage import save_video_clip_async
from src.services.stream_utils import display_frame, setup_window, teardown_windows
from src.services.stream_security import mask_credentials

LOGGER.setLevel("ERROR")

_model = None


def get_model():
    """Lazily load the custom shoplifting model so a missing weight file
    only fails this task, instead of crashing the whole Celery worker."""
    global _model
    if _model is None:
        model_path = os.getenv("SHOPLIFTING_MODEL_PATH", "src/trained-models/shoplifting_best.pt")
        _model = YOLO(model_path)
        _model.conf = 0.7
    return _model


SHOPLIFTING_FRAME_SKIP = max(1, int(os.getenv("SHOPLIFTING_FRAME_SKIP", "2")))


@celery.task(bind=True, base=AbortableTask, name="tasks.process_detect_shoplifting")
def detect_shoplifting_async(self, rtsp_url, camera_id=None):
    print(f"Starting detect shoplifting for {mask_credentials(rtsp_url)}")
    cap = None

    try:
        model = get_model()

        cap = cv2.VideoCapture(rtsp_url)
        if not cap.isOpened():
            print("Error: Could not open video stream.")
            return

        # Get video properties
        FRAME_RATE = int(cap.get(cv2.CAP_PROP_FPS) or 0)
        if FRAME_RATE <= 0 or FRAME_RATE > 120:
            FRAME_RATE = 25  # sensible default for RTSP streams with unknown fps
        FRAME_WIDTH = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0) or 1280
        FRAME_HEIGHT = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0) or 720

        print(f"Frame rate: {FRAME_RATE} Frame width: {FRAME_WIDTH} Frame height: {FRAME_HEIGHT}")

        BUFFER_SIZE = FRAME_RATE * 2  # Store last 2 seconds of frames
        AFTER_BUFFER_SIZE = FRAME_RATE * 2  # Store next 2 seconds of frames
        video_queue = collections.deque(maxlen=BUFFER_SIZE)

        recording = False
        frames_to_save = []
        save_start_frame_count = 0

        output_folder = os.getenv("SAVED_CLIPS_DIR", "saved_clips")
        os.makedirs(output_folder, exist_ok=True)

        frame_count = 0

        # Desktop preview window (no-op when running headless on a server)
        setup_window("Shoplifting Detection", cv2.WINDOW_AUTOSIZE)

        while cap.isOpened():
            # Check if the task has been aborted
            if self.is_aborted():
                print("Task aborted: Shoplifting detection stopped.")
                break

            ret, frame = cap.read()
            if not ret:
                print("Error: Failed to grab frame.")
                break

            frame_count += 1
            video_queue.append(frame)

            # Process model every Nth frame to reduce load
            if frame_count % SHOPLIFTING_FRAME_SKIP == 0:
                results = model(frame)
            else:
                results = []  # Empty results for non-processing frames

            # Process detection results
            for result in results:
                boxes = result.boxes  # Bounding boxes
                confidences = boxes.conf.cpu().numpy()  # Confidence scores
                class_ids = boxes.cls.cpu().numpy()  # Class IDs
                names = model.names  # Class names dictionary

                for i, conf in enumerate(confidences):
                    if names[int(class_ids[i])] == "Shoplifting":
                        print(
                            f"========== Shoplifting Detected at Frame {frame_count} "
                            f"with {conf} confidences =========="
                        )
                    if conf >= 0.3:  # Check confidence threshold
                        detected_class = names[int(class_ids[i])]
                        if detected_class == "Shoplifting" and not recording:
                            print(f"Shoplifting detected with confidence: {conf}")

                            # Start recording
                            recording = True
                            frames_to_save = list(video_queue)  # Save past 2 seconds of frames
                            save_start_frame_count = frame_count  # Mark the frame where detection started


            # Show window (desktop) or publish frame for live streaming (headless)
            if display_frame(
                "Shoplifting Detection", frame, camera_id=camera_id, owner=self.request.id
            ):
                print("User quit with 'q'.")
                break

            if recording:
                frames_to_save.append(frame)

                # Stop recording after next 2 seconds worth of frames (total 4 seconds including buffer)
                if frame_count - save_start_frame_count >= AFTER_BUFFER_SIZE:
                    recording = False
                    print("Saving 4-second video clip...")

                    filename = os.path.join(output_folder, f"shoplifting_{int(time.time())}.mp4")
                    # Save asynchronously with low-latency encoder settings (faststart, no B-frames via ffmpeg if available)
                    save_video_clip_async(
                        frames=frames_to_save,
                        fps=FRAME_RATE,
                        frame_size=(FRAME_WIDTH, FRAME_HEIGHT),
                        output_path=filename,
                        use_ffmpeg=True,
                        container="mp4",
                        preset="veryfast",
                        gop=FRAME_RATE
                    )
                    print(f"Saving asynchronously: {filename}")

                    frames_to_save.clear()

    except Exception as e:
        print(f"Error in shoplifting detection: {e}")

    finally:
        if cap is not None:  # Only release cap if it was initialized
            cap.release()
        teardown_windows()
        print("Stopped shoplifting detection.")
