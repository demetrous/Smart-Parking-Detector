"""Street-view calibration schema for fixed image/video cameras.

The calibration maps stable image/video pixels to known map coordinates and
defines parking-slot polygons in the same media coordinate system.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field


class ReferencePoint(BaseModel):
    id: str | None = None
    label: str | None = None
    pixel: tuple[float, float]
    lat: float
    lng: float


class ParkingSlotCalibration(BaseModel):
    id: str
    lat: float
    lng: float
    polygon: list[tuple[float, float]] = Field(min_length=3)


class ScaleReferenceMeters(BaseModel):
    pixelA: tuple[float, float]
    pixelB: tuple[float, float]
    meters: float = Field(gt=0)


class StreetCalibration(BaseModel):
    schema_version: int = 1
    camera_id: str
    frame_size: tuple[int, int]
    reference_points: list[ReferencePoint] = Field(default_factory=list)
    parking_slots: list[ParkingSlotCalibration] = Field(default_factory=list)
    scale_reference_meters: ScaleReferenceMeters | None = None


def load_street_calibration(path: str | Path) -> StreetCalibration:
    return StreetCalibration.model_validate_json(Path(path).read_text(encoding="utf-8"))


def dump_street_calibration(calibration: StreetCalibration, path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(calibration.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
