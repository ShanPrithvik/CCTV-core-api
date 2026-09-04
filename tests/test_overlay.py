import numpy as np

from src.services.overlay import (
    PROCESS_HEIGHT,
    PROCESS_WIDTH,
    build_roi_mask,
    draw_rule_legend,
    point_in_mask,
    roi_points,
    style_for,
)


def test_styles_are_distinct():
    colors = {tuple(style_for(name)["bgr"]) for name in (
        "CROWD_DETECTION",
        "RESTRICTED_AREA",
        "SHOPLIFTING",
    )}
    assert len(colors) == 3


def test_roi_mask_matches_processed_frame_size():
    roi = [
        {"x": 10, "y": 10},
        {"x": 200, "y": 10},
        {"x": 200, "y": 200},
        {"x": 10, "y": 200},
    ]
    mask, pts = build_roi_mask(roi)
    assert mask.shape == (PROCESS_HEIGHT, PROCESS_WIDTH)
    assert point_in_mask(mask, 50, 50)
    assert not point_in_mask(mask, 400, 400)
    assert pts.shape[-1] == 2


def test_roi_points_clamp_out_of_range():
    points = roi_points([{"x": -20, "y": 9000}, {"x": 50, "y": 50}])
    assert points[0] == (0, PROCESS_HEIGHT - 1)
    assert points[1] == (50, 50)


def test_legend_draws_without_overlapping_origin():
    frame = np.zeros((PROCESS_HEIGHT, PROCESS_WIDTH, 3), dtype=np.uint8)
    rules = [
        {"name": "Crowd", "model_type": "CROWD_DETECTION"},
        {"name": "Zone", "model_type": "RESTRICTED_AREA"},
        {"name": "Theft", "model_type": "SHOPLIFTING"},
    ]
    draw_rule_legend(frame, rules)
    # Legend lives on the right; the LIVE badge sits top-left in the UI.
    assert frame[20, 20].sum() == 0
    assert frame[20, PROCESS_WIDTH - 30].sum() > 0
