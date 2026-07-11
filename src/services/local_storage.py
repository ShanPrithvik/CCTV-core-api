import os
import shutil
import subprocess
import threading
from io import BytesIO
from typing import List, Tuple, Optional

try:
    import cv2
except Exception:
    cv2 = None


def save_to_local_storage(screenshot_buffer: BytesIO, file_name, save_directory=r"D:\CCTV_FE_BE\cctv_snip"):
    """
    Saves an in-memory file (BytesIO buffer) to the specified local file system path.

    Args:
        screenshot_buffer (io.BytesIO): The buffer containing the file data.
        file_name (str): The name of the file to save.
        save_directory (str): Full path where the file should be saved.

    This function writes the buffer content to a file at the given path.
    """
    # Ensure the save directory exists
    os.makedirs(save_directory, exist_ok=True)

    # Full path to save the file
    file_path = os.path.join(save_directory, file_name)

    # Write the buffer to file
    with open(file_path, "wb") as f:
        f.write(screenshot_buffer.getbuffer())

    print(f"Saved screenshot to: {file_path}")


def _ensure_parent_dir(path: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)


def is_ffmpeg_available() -> bool:
    """Return True if ffmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def save_video_clip(
    frames: List,
    fps: int,
    frame_size: Tuple[int, int],
    output_path: str,
    use_ffmpeg: bool = True,
    container: str = "mp4",
    preset: str = "veryfast",
    gop: Optional[int] = None,
) -> str:
    """
    Save a list of BGR frames to a video file with low-latency settings.

    Prefers FFmpeg/libx264 with zerolatency and faststart (for mp4), and falls back to OpenCV.

    Args:
        frames: list of numpy.ndarray frames in BGR format.
        fps: frames per second.
        frame_size: (width, height).
        output_path: final file path (extension will be normalized to match container).
        use_ffmpeg: prefer FFmpeg if available.
        container: "mp4" or "mkv".
        preset: FFmpeg preset (ultrafast/veryfast/fast/...).
        gop: keyframe interval; defaults to fps if None.

    Returns:
        The absolute path to the saved file.
    """
    if not frames:
        raise ValueError("save_video_clip: frames list is empty")

    width, height = frame_size
    fps = max(int(fps or 0), 1)
    gop = int(gop) if gop is not None else fps

    # Normalize extension to match container
    base, ext = os.path.splitext(output_path)
    container = (container or "mp4").lower()
    if container == "mkv":
        output_path = base + ".mkv"
    else:
        container = "mp4"
        output_path = base + ".mp4"

    output_path = os.path.abspath(output_path)
    _ensure_parent_dir(output_path)

    if use_ffmpeg and is_ffmpeg_available():
        # Build FFmpeg command
        cmd = [
            "ffmpeg",
            "-loglevel", "error",
            "-y",
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{width}x{height}",
            "-r", str(fps),
            "-i", "pipe:0",
            "-an",
            "-c:v", "libx264",
            "-preset", preset,
            "-tune", "zerolatency",
            "-bf", "0",
            "-g", str(gop),
            "-keyint_min", str(gop),
            "-sc_threshold", "0",
            "-pix_fmt", "yuv420p",
        ]
        if container == "mp4":
            cmd += ["-movflags", "+faststart"]
        cmd += [output_path]

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            for frame in frames:
                # Expect frame in BGR (np.ndarray, HxWx3)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            proc.wait(timeout=180)
            return output_path
        except Exception as e:
            print(f"FFmpeg writer failed ({e}). Falling back to OpenCV VideoWriter.")
            # Fall through to OpenCV

    if cv2 is None:
        raise RuntimeError("Neither FFmpeg available nor OpenCV present to write video.")

    # OpenCV fallback: MP4 (mp4v). Note: moov atom at end; still instant local open after finalize.
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
    if not out.isOpened():
        raise RuntimeError(f"OpenCV VideoWriter failed to open file: {output_path}")
    for frame in frames:
        out.write(frame)
    out.release()
    return output_path


def save_video_clip_async(
    frames: List,
    fps: int,
    frame_size: Tuple[int, int],
    output_path: str,
    use_ffmpeg: bool = True,
    container: str = "mp4",
    preset: str = "veryfast",
    gop: Optional[int] = None,
) -> threading.Thread:
    """
    Save frames asynchronously to avoid blocking the capture/inference loop.
    """
    frames_copy = list(frames)

    def _worker():
        try:
            save_video_clip(
                frames_copy,
                fps=fps,
                frame_size=frame_size,
                output_path=output_path,
                use_ffmpeg=use_ffmpeg,
                container=container,
                preset=preset,
                gop=gop,
            )
        except Exception as e:
            print(f"Async save failed: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
