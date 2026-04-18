"""Slot configuration loader.

A slot config JSON file describes the parking slots visible to one camera:

    {
        "camera_id": "cam_1",
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
import os
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
    """Slot geometry per camera. Backend URL belongs in CLI or PARKINGSPOTTER_BACKEND_URL."""

    camera_id: str
    slots: list[SlotConfig] = field(default_factory=list)
    legacy_backend_url: str | None = None


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

    legacy = data.get("backend_url")
    if legacy is not None:
        legacy = str(legacy).strip() or None

    return CameraConfig(
        camera_id=data["camera_id"],
        slots=slots,
        legacy_backend_url=legacy,
    )


def resolve_backend_url(cli_backend_url: str | None, cfg: CameraConfig) -> str:
    """Precedence: CLI --backend-url → PARKINGSPOTTER_BACKEND_URL → legacy slots.json field → localhost."""
    if cli_backend_url and str(cli_backend_url).strip():
        return str(cli_backend_url).strip().rstrip("/")
    env = os.getenv("PARKINGSPOTTER_BACKEND_URL", "").strip()
    if env:
        return env.rstrip("/")
    if cfg.legacy_backend_url:
        return cfg.legacy_backend_url.rstrip("/")
    return "http://127.0.0.1:8000"
