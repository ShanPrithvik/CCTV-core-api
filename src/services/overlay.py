"""Shared live-view drawing: colors, ROI masks, and stacked rule overlays.

Every detection rule used to decode the camera independently and burn its own
picture. The camera pipeline instead evaluates every active rule against one
resized frame and draws them all here, so the live view can show a combined
picture without two publishers fighting over the same Redis key.
"""
import cv2
import numpy as np

PROCESS_WIDTH = 1280
PROCESS_HEIGHT = 720
PROCESS_SIZE = (PROCESS_WIDTH, PROCESS_HEIGHT)

# BGR colors chosen so the three rule types stay distinguishable even when
# their ROIs overlap. Crowd stays red (legacy), restricted is orange, and
# shoplifting is yellow because that model previously drew nothing at all.
RULE_STYLES = {
    "CROWD_DETECTION": {
        "bgr": (0, 0, 255),
        "box": (0, 255, 0),
        "label": "CROWD",
    },
    "RESTRICTED_AREA": {
        "bgr": (0, 140, 255),
        "box": (255, 220, 0),
        "label": "RESTRICTED",
    },
    "SHOPLIFTING": {
        "bgr": (0, 255, 255),
        "box": (0, 255, 255),
        "label": "SHOPLIFTING",
    },
}


def style_for(model_type: str) -> dict:
    return RULE_STYLES.get(model_type, RULE_STYLES["CROWD_DETECTION"])


def roi_points(roi, width=PROCESS_WIDTH, height=PROCESS_HEIGHT):
    """Clamp ROI vertices into the processed-frame coordinate space."""
    points = []
    for point in roi or []:
        x = int(round(float(point["x"])))
        y = int(round(float(point["y"])))
        points.append(
            (
                max(0, min(width - 1, x)),
                max(0, min(height - 1, y)),
            )
        )
    return points


def build_roi_mask(roi, width=PROCESS_WIDTH, height=PROCESS_HEIGHT):
    """Build a filled mask after the frame has already been resized.

    Masks used to be built at the capture resolution and then tested against a
    1280x720 frame, which silently mis-registered every ROI that was not
    already 1280x720.
    """
    mask = np.zeros((height, width), dtype=np.uint8)
    points = roi_points(roi, width, height)
    if len(points) < 3:
        return mask, np.array(points, dtype=np.int32)
    pts = np.array([points], dtype=np.int32)
    cv2.fillPoly(mask, pts, 255)
    return mask, pts


def point_in_mask(mask, x: int, y: int) -> bool:
    return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and mask[y, x] > 0


def draw_roi(frame, pts, color):
    if pts is None or len(pts) == 0:
        return
    cv2.polylines(frame, pts, isClosed=True, color=color, thickness=2)


def draw_box(frame, x1, y1, x2, y2, color, text=None):
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
    if text:
        cv2.putText(
            frame,
            text,
            (x1, max(y1 - 8, 16)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
        )


def draw_rule_legend(frame, rules):
    """Paint a compact chip strip so the viewer can see every active rule."""
    if not rules:
        return
    x = frame.shape[1] - 12
    y = 28
    for rule in reversed(rules):
        style = style_for(rule["model_type"])
        label = f"{style['label']}: {rule['name']}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        chip_w = tw + 28
        x1 = x - chip_w
        cv2.rectangle(frame, (x1, y - 16), (x, y + 8), (20, 20, 20), -1)
        cv2.rectangle(frame, (x1 + 6, y - 8), (x1 + 16, y + 2), style["bgr"], -1)
        cv2.putText(
            frame,
            label,
            (x1 + 22, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (240, 240, 240),
            1,
        )
        y += 28


def draw_alert_banners(frame, banners):
    """Stack alert text under the top edge, clear of the frontend LIVE badge."""
    y = 110
    for text, color in banners:
        (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.9, 2)
        x = max((frame.shape[1] - tw) // 2, 0)
        cv2.putText(frame, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
        y += 36
