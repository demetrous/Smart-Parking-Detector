from __future__ import annotations

import sys
from pathlib import Path

import pytest

# draw_slots imports `calibration` from the detector tool directory
_DETECTOR_TOOL_DIR = Path(__file__).resolve().parents[1]
if str(_DETECTOR_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_DETECTOR_TOOL_DIR))

from calibration import GeoCalibration, local_m_to_latlng  # noqa: E402


def _square_calibration_dict(lat0: float, lng0: float) -> dict:
    """Four corners: pixel (u,v) ↔ local meters (u,v) via matching lat/lng."""
    corners_px = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]
    ref = []
    for u, v in corners_px:
        la, ln = local_m_to_latlng(u, v, lat0, lng0)
        ref.append({"pixel": [u, v], "lat": la, "lng": ln})
    return {"camera_id": "cam_test", "reference_points": ref}


def test_homography_round_trip_corners() -> None:
    data = _square_calibration_dict(47.0, -122.0)
    cal = GeoCalibration.from_dict(data)
    for pt in data["reference_points"]:
        u, v = pt["pixel"]
        la, ln = cal.pixel_to_lat_lng(u, v)
        assert la == pytest.approx(pt["lat"], abs=1e-4)
        assert ln == pytest.approx(pt["lng"], abs=1e-4)


def test_requires_four_points() -> None:
    data = _square_calibration_dict(1.0, 2.0)
    data["reference_points"] = data["reference_points"][:3]
    with pytest.raises(ValueError, match="at least 4"):
        GeoCalibration.from_dict(data)


def test_requires_camera_id() -> None:
    data = _square_calibration_dict(1.0, 2.0)
    data["camera_id"] = ""
    with pytest.raises(ValueError, match="camera_id"):
        GeoCalibration.from_dict(data)
