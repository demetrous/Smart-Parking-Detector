from __future__ import annotations

import importlib
import sys
import types

import numpy as np

fake_ultralytics = types.ModuleType("ultralytics")
fake_ultralytics.YOLO = object
sys.modules.setdefault("ultralytics", fake_ultralytics)

from detector.detector.config import SlotConfig

inference = importlib.import_module("detector.detector.inference")


class FakeResult:
    def __init__(self, boxes: list[object]) -> None:
        self.boxes = boxes


class FakeBox:
    def __init__(self, cls_id: int, bbox: tuple[float, float, float, float]) -> None:
        self.cls = np.array([cls_id], dtype=float)
        self.xyxy = np.array([bbox], dtype=float)


class FakeYOLO:
    def __init__(self, frames: list[list[FakeResult]]) -> None:
        self._frames = frames
        self._idx = 0

    def __call__(self, frame: np.ndarray, verbose: bool = False) -> list[FakeResult]:
        if self._idx >= len(self._frames):
            return []
        result = self._frames[self._idx]
        self._idx += 1
        return result


def _slot() -> SlotConfig:
    return SlotConfig(
        id="A1",
        lat=47.62319,
        lng=-122.3546,
        polygon=[[0, 0], [10, 0], [10, 10], [0, 10]],
    )


def _frame() -> np.ndarray:
    return np.zeros((32, 32, 3), dtype=np.uint8)


def test_process_frame_respects_iou_threshold(monkeypatch) -> None:
    overlapping_box = FakeBox(2, (5, 0, 15, 10))
    monkeypatch.setattr(
        inference,
        "YOLO",
        lambda model_name: FakeYOLO([[FakeResult([overlapping_box])]]),
    )
    updates: list[tuple[str, str, float]] = []

    detector = inference.OccupancyDetector(
        slots=[_slot()],
        iou_threshold=0.4,
        debounce_frames=1,
        on_update=lambda slot_id, status, confidence: updates.append((slot_id, status, confidence)),
    )

    detector.process_frame(_frame())

    assert updates == []
    assert detector._states["A1"].current_status == "available"


def test_process_frame_emits_debounced_occupancy_transitions(monkeypatch) -> None:
    occupied_box = FakeBox(2, (0, 0, 10, 10))
    monkeypatch.setattr(
        inference,
        "YOLO",
        lambda model_name: FakeYOLO(
            [
                [FakeResult([occupied_box])],
                [FakeResult([occupied_box])],
                [],
                [],
            ]
        ),
    )
    updates: list[tuple[str, str, float]] = []

    detector = inference.OccupancyDetector(
        slots=[_slot()],
        iou_threshold=0.25,
        debounce_frames=2,
        on_update=lambda slot_id, status, confidence: updates.append((slot_id, status, confidence)),
    )

    detector.process_frame(_frame())
    assert updates == []
    assert detector._states["A1"].current_status == "available"

    detector.process_frame(_frame())
    assert updates == [("A1", "occupied", 1.0)]
    assert detector._states["A1"].current_status == "occupied"

    detector.process_frame(_frame())
    assert updates == [("A1", "occupied", 1.0)]

    detector.process_frame(_frame())
    assert updates == [("A1", "occupied", 1.0), ("A1", "available", 1.0)]
    assert detector._states["A1"].current_status == "available"
