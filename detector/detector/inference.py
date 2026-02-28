"""YOLO11 inference + per-slot IoU occupancy logic.

How occupancy is determined (plain mode, default)
--------------------------------------------------
1. Run YOLO11 on the frame → get bounding boxes for vehicle classes.
2. For each parking slot:
   a. Convert the slot polygon to a bounding box (min/max x, y).
   b. Compute IoU between the slot bbox and every detected vehicle bbox.
   c. If any IoU exceeds `iou_threshold` → slot is OCCUPIED.
3. Debounce: only change a slot's published status after `debounce_frames`
   consecutive frames agree on the new status.
4. When a slot transitions occupied → available (or available → occupied),
   publish a POST to the backend.

How "soon" is detected (tracking mode, --track flag)
------------------------------------------------------
When `enable_tracking=True` the detector uses ``model.track()`` (ByteTrack) so
each detected vehicle gets a persistent integer ID across frames.

For every slot that is currently "occupied" the detector monitors the centroid
of the covering vehicle's track over a rolling window:

  • If the centroid moves more than ``motion_threshold_px`` pixels across the
    window → the car is pulling out → publish status **"soon"**.
  • If the centroid stops moving again → revert to **"occupied"**.
  • When the vehicle fully leaves (IoU drops below threshold) → the normal
    debounce drives the transition to **"available"**.

The plain-mode debounce still runs in the background in tracking mode (on the
raw IoU signal), so "available" transitions remain stable regardless of tracking.

Vehicle COCO class IDs used
---------------------------
    2  car
    3  motorcycle
    5  bus
    7  truck
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import cv2
import numpy as np
from ultralytics import YOLO

from .config import SlotConfig
from .tracker import MotionMonitor

# COCO class IDs that count as a vehicle occupying a spot
VEHICLE_CLASSES = {2, 3, 5, 7}

SpotStatus = str  # "available" | "soon" | "occupied"

# BGR colours for the preview window
_STATUS_COLOUR = {
    "available": (0, 200, 0),    # green
    "soon":      (0, 180, 220),  # yellow-ish (BGR)
    "occupied":  (0, 0, 220),    # red
}


def _bbox_from_polygon(polygon: list[list[int]]) -> tuple[float, float, float, float]:
    """Return (x1, y1, x2, y2) bounding box enclosing the polygon."""
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    return float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection-over-Union for two (x1, y1, x2, y2) boxes."""
    ix1 = max(a[0], b[0])
    iy1 = max(a[1], b[1])
    ix2 = min(a[2], b[2])
    iy2 = min(a[3], b[3])

    inter_w = max(0.0, ix2 - ix1)
    inter_h = max(0.0, iy2 - iy1)
    inter = inter_w * inter_h

    if inter == 0.0:
        return 0.0

    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _point_in_polygon(x: float, y: float, polygon: list[list[int]]) -> bool:
    """Ray-casting point-in-polygon test."""
    pts = np.array(polygon, dtype=np.float32)
    return cv2.pointPolygonTest(pts, (x, y), measureDist=False) >= 0


@dataclass
class SlotState:
    config: SlotConfig
    current_status: SpotStatus = "available"
    # Debounce fields — track the raw IoU signal independently of current_status
    # so the "available" transition stays stable even when status is "soon".
    _candidate: SpotStatus = field(default="available", init=False, repr=False)
    _streak: int = field(default=0, init=False, repr=False)
    _debounced_occupied: bool = field(default=False, init=False, repr=False)


class OccupancyDetector:
    """Run YOLO11 frame-by-frame and emit status changes for parking slots.

    Parameters
    ----------
    slots:
        Slot configs from the camera config file.
    model_name:
        Ultralytics model name or path.  ``"yolo11n.pt"`` is the nano variant
        (fast, small).  Use ``"yolo11s.pt"`` or larger for better accuracy.
    iou_threshold:
        Minimum IoU between a vehicle bbox and a slot bbox to consider the
        slot occupied.
    debounce_frames:
        Consecutive frames required before a status change is emitted.
    on_update:
        Callback ``(slot_id, new_status, confidence)`` fired when a slot's
        confirmed status changes.
    enable_tracking:
        When True, use ByteTrack (``model.track()``) and enable motion-based
        "soon" detection.  Requires ``lapx`` or ``lap`` for best performance
        (falls back to scipy if neither is installed).
    motion_window_frames:
        Rolling window size (frames) for centroid-displacement tracking.
        Larger = more stable but slower to react.
    motion_threshold_px:
        Centroid displacement (pixels) over the window required to flag a
        vehicle as moving.  Tune per camera resolution / parking-lot scale.
    """

    def __init__(
        self,
        slots: list[SlotConfig],
        model_name: str = "yolo11n.pt",
        iou_threshold: float = 0.25,
        debounce_frames: int = 3,
        on_update: Callable[[str, SpotStatus, float], None] | None = None,
        enable_tracking: bool = False,
        motion_window_frames: int = 10,
        motion_threshold_px: float = 15.0,
    ) -> None:
        self.iou_threshold = iou_threshold
        self.debounce_frames = debounce_frames
        self.on_update = on_update
        self._enable_tracking = enable_tracking

        self._model = YOLO(model_name)
        self._states = {s.id: SlotState(config=s) for s in slots}
        self._motion: MotionMonitor | None = (
            MotionMonitor(
                window_frames=motion_window_frames,
                motion_threshold_px=motion_threshold_px,
            )
            if enable_tracking
            else None
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_frame(self, frame: np.ndarray) -> None:
        """Run detection (and optionally tracking) on one frame."""
        if self._enable_tracking:
            self._process_tracked(frame)
        else:
            self._process_plain(frame)

    def annotate_frame(self, frame: np.ndarray) -> np.ndarray:
        """Draw slot polygons and status labels on a copy of the frame."""
        out = frame.copy()
        for state in self._states.values():
            pts = np.array(state.config.polygon, dtype=np.int32)
            color = _STATUS_COLOUR.get(state.current_status, (128, 128, 128))
            cv2.polylines(out, [pts], isClosed=True, color=color, thickness=2)
            cx = int(np.mean([p[0] for p in state.config.polygon]))
            cy = int(np.mean([p[1] for p in state.config.polygon]))
            cv2.putText(
                out,
                f"{state.config.id}: {state.current_status}",
                (cx - 20, cy),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
        return out

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process_plain(self, frame: np.ndarray) -> None:
        """Original IoU-only occupancy logic (no tracking)."""
        results = self._model(frame, verbose=False)
        vehicle_bboxes: list[tuple[float, float, float, float]] = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0].item())
                if cls_id not in VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                vehicle_bboxes.append((x1, y1, x2, y2))

        for state in self._states.values():
            slot_bbox = _bbox_from_polygon(state.config.polygon)
            occupied = any(
                _iou(slot_bbox, vb) >= self.iou_threshold for vb in vehicle_bboxes
            )
            new_candidate: SpotStatus = "occupied" if occupied else "available"
            confidence = 1.0

            if new_candidate == state._candidate:
                state._streak += 1
            else:
                state._candidate = new_candidate
                state._streak = 1

            if (
                state._streak >= self.debounce_frames
                and new_candidate != state.current_status
            ):
                state.current_status = new_candidate
                if self.on_update:
                    self.on_update(state.config.id, new_candidate, confidence)

    def _process_tracked(self, frame: np.ndarray) -> None:
        """ByteTrack-based occupancy + motion detection."""
        assert self._motion is not None

        results = self._model.track(
            frame, persist=True, tracker="bytetrack.yaml", verbose=False
        )

        # track_id → bbox mapping for this frame
        tracked: dict[int, tuple[float, float, float, float]] = {}
        active_ids: set[int] = set()

        for result in results:
            if result.boxes is None:
                continue
            ids = result.boxes.id
            for i, box in enumerate(result.boxes):
                cls_id = int(box.cls[0].item())
                if cls_id not in VEHICLE_CLASSES:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                bbox = (x1, y1, x2, y2)
                if ids is not None:
                    tid = int(ids[i].item())
                    tracked[tid] = bbox
                    active_ids.add(tid)
                    self._motion.update(tid, bbox)

        self._motion.prune(active_ids)

        for state in self._states.values():
            slot_bbox = _bbox_from_polygon(state.config.polygon)

            # Find the vehicle track with the highest IoU over this slot
            best_tid: int | None = None
            best_iou = 0.0
            for tid, vbbox in tracked.items():
                iou = _iou(slot_bbox, vbbox)
                if iou > best_iou:
                    best_iou = iou
                    best_tid = tid

            raw_occupied = best_iou >= self.iou_threshold
            raw_candidate: SpotStatus = "occupied" if raw_occupied else "available"

            # Run the debounce on the raw IoU signal so the "available"
            # transition stays stable even while status is temporarily "soon".
            if raw_candidate == state._candidate:
                state._streak += 1
            else:
                state._candidate = raw_candidate
                state._streak = 1

            if state._streak >= self.debounce_frames:
                state._debounced_occupied = raw_occupied

            # Determine the desired published status
            if state._debounced_occupied:
                if best_tid is not None and self._motion.is_moving(best_tid):
                    desired: SpotStatus = "soon"
                else:
                    desired = "occupied"
            else:
                desired = "available"

            if desired != state.current_status:
                state.current_status = desired
                confidence = best_iou if best_iou > 0 else 0.9
                if self.on_update:
                    self.on_update(state.config.id, desired, confidence)
