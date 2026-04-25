from __future__ import annotations

from detector.detector.street_calibration import StreetCalibration


def test_street_calibration_schema_accepts_anchor_points_and_slots() -> None:
    calibration = StreetCalibration.model_validate(
        {
            "camera_id": "first_ave",
            "frame_size": [1920, 1080],
            "reference_points": [
                {"pixel": [100, 200], "lat": 47.1, "lng": -122.1},
                {"pixel": [500, 200], "lat": 47.1, "lng": -122.0},
                {"pixel": [500, 700], "lat": 47.0, "lng": -122.0},
                {"pixel": [100, 700], "lat": 47.0, "lng": -122.1},
            ],
            "parking_slots": [
                {
                    "id": "A1",
                    "lat": 47.05,
                    "lng": -122.05,
                    "polygon": [[110, 500], [220, 500], [220, 620], [110, 620]],
                }
            ],
            "scale_reference_meters": {
                "pixelA": [110, 500],
                "pixelB": [220, 500],
                "meters": 6.0,
            },
        }
    )

    assert calibration.camera_id == "first_ave"
    assert calibration.parking_slots[0].id == "A1"
    assert calibration.scale_reference_meters is not None
