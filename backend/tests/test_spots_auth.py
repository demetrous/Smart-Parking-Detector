from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import main

SECRET = "test-shared-secret"


def _signed_headers(raw_body: bytes, timestamp: str) -> dict[str, str]:
    digest = hmac.new(
        SECRET.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-ParkingSpotter-Timestamp": timestamp,
        "X-ParkingSpotter-Signature": digest,
    }


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, list, list]:
    stored: list = []
    broadcasted: list = []

    async def fake_init_db() -> None:
        return None

    async def fake_load_spots_db() -> list:
        return []

    async def fake_background_loop() -> None:
        return None

    async def fake_upsert(spot, persist: bool = True) -> None:  # type: ignore[no-untyped-def]
        stored.append((spot, persist))

    async def fake_broadcast(event) -> None:  # type: ignore[no-untyped-def]
        broadcasted.append(event)

    monkeypatch.setenv("PARKINGSPOTTER_SHARED_SECRET", SECRET)
    monkeypatch.setenv("PARKINGSPOTTER_MAX_SIGNATURE_AGE_SECONDS", "30")
    monkeypatch.setattr(main, "init_db", fake_init_db)
    monkeypatch.setattr(main, "load_spots_db", fake_load_spots_db)
    monkeypatch.setattr(main, "simulator_loop", fake_background_loop)
    monkeypatch.setattr(main, "dwell_checker_loop", fake_background_loop)
    monkeypatch.setattr(main.store, "upsert", fake_upsert)
    monkeypatch.setattr(main.hub, "broadcast", fake_broadcast)

    app = main.create_app()
    with TestClient(app) as test_client:
        stored.clear()
        broadcasted.clear()
        yield test_client, stored, broadcasted


def test_post_spots_accepts_valid_signature(client: tuple[TestClient, list, list]) -> None:
    test_client, stored, broadcasted = client
    payload = {
        "id": "A1",
        "lat": 47.62319,
        "lng": -122.3546,
        "status": "occupied",
        "confidence": 0.95,
        "updatedAt": "2026-04-18T12:00:00+00:00",
        "cameraId": "cam_1",
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = datetime.now(timezone.utc).isoformat()

    response = test_client.post("/spots", content=raw_body, headers=_signed_headers(raw_body, timestamp))

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(stored) == 1
    assert stored[0][0].id == "A1"
    assert len(broadcasted) == 1


def test_post_spots_rejects_missing_signature_headers(client: tuple[TestClient, list, list]) -> None:
    test_client, stored, broadcasted = client
    payload = {
        "id": "A1",
        "lat": 47.62319,
        "lng": -122.3546,
        "status": "occupied",
        "confidence": 0.95,
        "updatedAt": "2026-04-18T12:00:00+00:00",
        "cameraId": "cam_1",
    }

    response = test_client.post("/spots", json=payload)

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing detector authentication headers"
    assert stored == []
    assert broadcasted == []


def test_post_spots_rejects_invalid_signature(client: tuple[TestClient, list, list]) -> None:
    test_client, stored, broadcasted = client
    payload = {
        "id": "A1",
        "lat": 47.62319,
        "lng": -122.3546,
        "status": "occupied",
        "confidence": 0.95,
        "updatedAt": "2026-04-18T12:00:00+00:00",
        "cameraId": "cam_1",
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = datetime.now(timezone.utc).isoformat()
    headers = _signed_headers(raw_body, timestamp)
    headers["X-ParkingSpotter-Signature"] = "not-the-right-signature"

    response = test_client.post("/spots", content=raw_body, headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid detector signature"
    assert stored == []
    assert broadcasted == []


def test_post_spots_rejects_stale_signature(client: tuple[TestClient, list, list]) -> None:
    test_client, stored, broadcasted = client
    payload = {
        "id": "A1",
        "lat": 47.62319,
        "lng": -122.3546,
        "status": "occupied",
        "confidence": 0.95,
        "updatedAt": "2026-04-18T12:00:00+00:00",
        "cameraId": "cam_1",
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    stale_timestamp = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()

    response = test_client.post(
        "/spots",
        content=raw_body,
        headers=_signed_headers(raw_body, stale_timestamp),
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Detector signature is stale"
    assert stored == []
    assert broadcasted == []
