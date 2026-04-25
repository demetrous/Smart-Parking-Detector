from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.hub import Hub
from app.models import Spot
from app.store import SpotStore


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pilot.db")
    monkeypatch.setenv("SIMULATOR", "false")
    monkeypatch.setattr(main, "store", SpotStore())
    monkeypatch.setattr(main, "hub", Hub())
    monkeypatch.setattr(main, "dwell_checker_loop", lambda: _noop_loop())
    app = main.create_app()
    with TestClient(app) as test_client:
        yield test_client


async def _noop_loop() -> None:
    return None


def test_analytics_summary_returns_utilization(client: TestClient) -> None:
    response = client.get("/analytics/summary")

    assert response.status_code == 200
    payload = response.json()
    assert payload["totalSpots"] >= 1
    assert set(payload["statusCounts"]) >= {"available", "soon", "occupied"}
    assert "dwellBySpot" in payload


def test_spots_csv_export(client: TestClient) -> None:
    response = client.get("/spots.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0] == "id,status,lat,lng,confidence,camera_id,updated_at"


def test_camera_health_reports_stale_observations(client: TestClient) -> None:
    stale = datetime.now(timezone.utc) - timedelta(minutes=5)
    fresh = datetime.now(timezone.utc)

    async def write_observations() -> None:
        await db.upsert_observation_db(
            Spot(
                id="A1",
                lat=47.0,
                lng=-122.0,
                status="occupied",
                confidence=0.9,
                updatedAt=stale,
                cameraId="cam_1",
            )
        )
        await db.upsert_observation_db(
            Spot(
                id="A2",
                lat=47.1,
                lng=-122.1,
                status="available",
                confidence=0.95,
                updatedAt=fresh,
                cameraId="cam_2",
            )
        )

    import anyio

    anyio.run(write_observations)

    response = client.get("/cameras?offline_after_seconds=60")

    assert response.status_code == 200
    cameras = {row["cameraId"]: row for row in response.json()}
    assert cameras["cam_1"]["online"] is False
    assert cameras["cam_2"]["online"] is True
    assert cameras["cam_1"]["observedSpotCount"] == 1
