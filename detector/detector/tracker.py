"""Motion monitor: centroid-history tracker for motion-based "soon" detection.

How it works
------------
ByteTrack assigns a persistent integer ID to each detected vehicle across frames.
For every active track we store a rolling window of its bounding-box centroids.
If the Euclidean distance between the *oldest* and *newest* centroid in that window
exceeds ``motion_threshold_px``, the vehicle is considered to be moving (pulling
out of a slot).

Parked cars stay within a few pixels of the same position (sensor noise / codec
jitter).  A car pulling out will typically shift 20–80 px over ~10 frames at
normal parking-lot frame rates (10–30 fps).
"""

from __future__ import annotations

from collections import deque

import numpy as np


def _centroid(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


class MotionMonitor:
    """Maintain a centroid history per ByteTrack ID and detect significant motion.

    Parameters
    ----------
    window_frames:
        Number of recent centroids to keep per track.  Larger values add
        latency but reduce sensitivity to momentary jitter.
    motion_threshold_px:
        Euclidean distance (pixels) between the oldest and newest centroid in
        the window required to flag the track as moving.
    """

    def __init__(
        self,
        window_frames: int = 10,
        motion_threshold_px: float = 15.0,
    ) -> None:
        self.window = window_frames
        self.threshold = motion_threshold_px
        self._history: dict[int, deque[tuple[float, float]]] = {}

    def update(self, track_id: int, bbox: tuple[float, float, float, float]) -> None:
        """Record the current centroid for a track."""
        if track_id not in self._history:
            self._history[track_id] = deque(maxlen=self.window)
        self._history[track_id].append(_centroid(bbox))

    def is_moving(self, track_id: int) -> bool:
        """Return True if this track displaced more than ``threshold`` px over its window."""
        hist = self._history.get(track_id)
        if hist is None or len(hist) < 2:
            return False
        oldest = np.array(hist[0])
        newest = np.array(hist[-1])
        return float(np.linalg.norm(newest - oldest)) >= self.threshold

    def displacement(self, track_id: int) -> float:
        """Return the centroid displacement (px) over the window, or 0.0 if unavailable."""
        hist = self._history.get(track_id)
        if hist is None or len(hist) < 2:
            return 0.0
        return float(np.linalg.norm(np.array(hist[-1]) - np.array(hist[0])))

    def prune(self, active_ids: set[int]) -> None:
        """Remove history entries for tracks that are no longer detected."""
        for tid in list(self._history):
            if tid not in active_ids:
                del self._history[tid]
