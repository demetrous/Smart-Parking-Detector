from __future__ import annotations

import importlib
import sys
import types

import numpy as np

fake_ultralytics = types.ModuleType("ultralytics")
fake_ultralytics.YOLO = object
sys.modules.setdefault("ultralytics", fake_ultralytics)

server = importlib.import_module("detector.detector.server")


class FakeScalar:
    def __init__(self, value: float) -> None:
        self.value = value

    def item(self) -> float:
        return self.value


class FakeVector:
    def __init__(self, values: list[float]) -> None:
        self.values = values

    def tolist(self) -> list[float]:
        return self.values


class FakeBox:
    def __init__(self, cls_id: int, conf: float, xyxy: list[float]) -> None:
        self.cls = [FakeScalar(cls_id)]
        self.conf = [FakeScalar(conf)]
        self.xyxy = [FakeVector(xyxy)]


class FakeResult:
    names = {2: "car", 0: "person"}

    def __init__(self) -> None:
        self.boxes = [
            FakeBox(2, 0.91, [10, 20, 110, 80]),
            FakeBox(0, 0.99, [1, 1, 2, 2]),
        ]


class FakeModel:
    names = {2: "car", 0: "person"}

    def __call__(self, frame, verbose: bool = False, conf: float = 0.25):
        return [FakeResult()]


def test_detect_vehicle_boxes_filters_vehicle_classes() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    response = server.detect_vehicle_boxes(FakeModel(), frame, conf=0.25)

    assert response.imageWidth == 200
    assert response.imageHeight == 100
    assert len(response.boxes) == 1
    assert response.boxes[0].className == "car"
    assert response.boxes[0].confidence == 0.91


def test_detect_boxes_can_include_people() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    response = server.detect_boxes(FakeModel(), frame, conf=0.25, include_people=True)

    assert [box.className for box in response.boxes] == ["car", "person"]


def test_detect_response_exposes_make_model_extension_point() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    response = server.detect_boxes(FakeModel(), frame, conf=0.25, include_people=True)

    assert response.experimental["makeModel"]["enabled"] is False


def test_detect_geometry_lines_returns_image_size() -> None:
    frame = np.zeros((100, 200, 3), dtype=np.uint8)

    response = server.detect_geometry_lines(frame)

    assert response.imageWidth == 200
    assert response.imageHeight == 100
    assert response.lines == []
