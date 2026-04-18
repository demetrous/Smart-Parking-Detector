from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import db
from app.models import Spot
from app.store import SpotStore


@pytest.mark.anyio
async def test_merge_uses_camera_priority_per_spot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    merge_path = tmp_path / "merge.json"
    merge_path.write_text(
        json.dumps({"default_priority": ["cam_1", "cam_2"], "per_spot": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGE_CONFIG_PATH", str(merge_path))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()

    store = SpotStore()
    t = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)

    changed1, c1 = await store.apply_detector_update(
        Spot(
            id="A1",
            lat=1.0,
            lng=2.0,
            status="available",
            confidence=0.9,
            updatedAt=t,
            cameraId="cam_2",
        )
    )
    assert changed1
    assert c1.status == "available"

    changed2, c2 = await store.apply_detector_update(
        Spot(
            id="A1",
            lat=1.0,
            lng=2.0,
            status="occupied",
            confidence=0.95,
            updatedAt=t,
            cameraId="cam_1",
        )
    )
    assert changed2
    assert c2.status == "occupied"
    assert c2.cameraId == "cam_1"

    cam_views = await store.list_for_camera("cam_2")
    assert len(cam_views) == 1
    assert cam_views[0].status == "available"


@pytest.mark.anyio
async def test_legacy_post_without_camera_id_updates_canonical_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()
    store = SpotStore()
    t = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)

    changed, canon = await store.apply_detector_update(
        Spot(
            id="B1",
            lat=10.0,
            lng=20.0,
            status="occupied",
            confidence=1.0,
            updatedAt=t,
            cameraId=None,
        )
    )
    assert changed
    assert canon.cameraId is None

    obs_rows = await db.load_observations_db()
    assert obs_rows == []
