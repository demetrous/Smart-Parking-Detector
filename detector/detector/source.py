"""Video source abstraction.

Wraps OpenCV VideoCapture so the rest of the detector doesn't care whether
the input is a webcam index, a local video file, or an RTSP stream.
"""

from __future__ import annotations

from typing import Generator

import cv2
import numpy as np


class VideoSource:
    """Yield BGR frames from any OpenCV-compatible source."""

    def __init__(self, source: str | int, skip_frames: int = 2) -> None:
        """
        Args:
            source: Webcam index (int), file path, or RTSP URL.
            skip_frames: Process every N-th frame to reduce CPU load.
                         1 = every frame, 2 = every other frame, etc.
        """
        self.source = source
        self.skip_frames = max(1, skip_frames)
        self._cap: cv2.VideoCapture | None = None

    def open(self) -> None:
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open video source: {self.source!r}")

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def frames(self) -> Generator[np.ndarray, None, None]:
        """Yield frames indefinitely; raises StopIteration when source ends."""
        if self._cap is None:
            self.open()
        assert self._cap is not None

        frame_idx = 0
        while True:
            ret, frame = self._cap.read()
            if not ret:
                return
            frame_idx += 1
            if frame_idx % self.skip_frames == 0:
                yield frame

    def __enter__(self) -> "VideoSource":
        self.open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
