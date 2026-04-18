"""Homography-based pixel → WGS84 calibration for slot authoring.

Loads a JSON artifact with 4+ ground-control points (pixel + lat/lng), fits a
planar homography in a local tangent plane, and converts image coordinates to
latitude/longitude. Used by draw_slots.py; the detector consumes the resulting
slots.json as before (lat/lng per slot).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

EARTH_RADIUS_M = 6_371_000.0


def latlng_to_local_m(lat: float, lng: float, lat0: float, lng0: float) -> tuple[float, float]:
    """Project (lat, lng) to local east/north meters relative to (lat0, lng0)."""
    dlat = math.radians(lat - lat0)
    dlng = math.radians(lng - lng0)
    x = EARTH_RADIUS_M * dlng * math.cos(math.radians(lat0))
    y = EARTH_RADIUS_M * dlat
    return x, y


def local_m_to_latlng(x: float, y: float, lat0: float, lng0: float) -> tuple[float, float]:
    """Inverse of latlng_to_local_m for small offsets."""
    lat = lat0 + math.degrees(y / EARTH_RADIUS_M)
    lng = lng0 + math.degrees(x / (EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lng


@dataclass(frozen=True)
class GeoCalibration:
    """Pixel → WGS84 via homography to a local meter plane."""

    camera_id: str
    H_pixel_to_local_m: np.ndarray
    lat0: float
    lng0: float

    def pixel_to_lat_lng(self, u: float, v: float) -> tuple[float, float]:
        src = np.array([[[float(u), float(v)]]], dtype=np.float64)
        dst = cv2.perspectiveTransform(src, self.H_pixel_to_local_m)
        x, y = float(dst[0, 0, 0]), float(dst[0, 0, 1])
        return local_m_to_latlng(x, y, self.lat0, self.lng0)

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, path_hint: str | None = None) -> GeoCalibration:
        loc = f" ({path_hint})" if path_hint else ""
        camera_id = str(data.get("camera_id", "")).strip()
        if not camera_id:
            raise ValueError(f"calibration JSON missing non-empty camera_id{loc}")

        raw_points = data.get("reference_points")
        if not isinstance(raw_points, list) or len(raw_points) < 4:
            raise ValueError(
                f"calibration needs reference_points: list of at least 4 entries{loc}"
            )

        pixels: list[list[float]] = []
        lats: list[float] = []
        lngs: list[float] = []
        for i, entry in enumerate(raw_points):
            if not isinstance(entry, dict):
                raise ValueError(f"reference_points[{i}] must be an object{loc}")
            pix = entry.get("pixel")
            lat = entry.get("lat")
            lng = entry.get("lng")
            if (
                not isinstance(pix, (list, tuple))
                or len(pix) != 2
                or not isinstance(lat, (int, float))
                or not isinstance(lng, (int, float))
            ):
                raise ValueError(
                    f"reference_points[{i}] needs pixel: [x,y], lat, lng (numbers){loc}"
                )
            pixels.append([float(pix[0]), float(pix[1])])
            lats.append(float(lat))
            lngs.append(float(lng))

        lat0 = sum(lats) / len(lats)
        lng0 = sum(lngs) / len(lngs)

        local_xy = np.array(
            [latlng_to_local_m(la, ln, lat0, lng0) for la, ln in zip(lats, lngs)],
            dtype=np.float64,
        )
        src_pts = np.array(pixels, dtype=np.float64)
        H, status = cv2.findHomography(
            src_pts,
            local_xy,
            method=cv2.RANSAC,
            ransacReprojThreshold=8.0,
        )
        if H is None:
            raise ValueError(f"cv2.findHomography failed — check collinear reference_points{loc}")

        inliers = int(status.sum()) if status is not None else len(pixels)
        if inliers < 4:
            raise ValueError(
                f"homography has only {inliers} inlier(s); need 4+ well-spread inliers{loc}"
            )

        return cls(
            camera_id=camera_id,
            H_pixel_to_local_m=H.astype(np.float64),
            lat0=lat0,
            lng0=lng0,
        )

    @classmethod
    def from_json_path(cls, path: Path) -> GeoCalibration:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"calibration file must be a JSON object: {path}")
        return cls.from_dict(data, path_hint=str(path))


def load_calibration_optional(path: Path | None) -> GeoCalibration | None:
    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"calibration file not found: {path}")
    return GeoCalibration.from_json_path(path)
