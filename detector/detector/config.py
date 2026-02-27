"""Slot configuration loader.

A slot config JSON file describes the parking slots visible to one camera:

    {
        "camera_id": "cam_1",
        "backend_url": "http://127.0.0.1:8000",
        "slots": [
            {
                "id": "A1",
                "lat": 47.623,
                "lng": -122.354,
                "polygon": [[120, 200], [180, 200], [180, 260], [120, 260]]
            }
        ]
    }

`polygon` is a list of [x, y] pixel coordinates in the camera frame that
define the parking slot region.  At least three points are required.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SlotConfig:
    id: str
    lat: float
    lng: float
    polygon: list[list[int]]  # [[x, y], ...]


@dataclass
class CameraConfig:
    camera_id: str
    backend_url: str
    slots: list[SlotConfig] = field(default_factory=list)


def load_config(path: str | Path) -> CameraConfig:
    """Parse and validate a slot config JSON file."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    slots = [
        SlotConfig(
            id=s["id"],
            lat=float(s["lat"]),
            lng=float(s["lng"]),
            polygon=s["polygon"],
        )
        for s in data["slots"]
    ]

    return CameraConfig(
        camera_id=data["camera_id"],
        backend_url=data.get("backend_url", "http://127.0.0.1:8000"),
        slots=slots,
    )
