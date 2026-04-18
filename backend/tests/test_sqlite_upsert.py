from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite
import pytest

from app import db
from app.models import Spot


@pytest.mark.anyio
async def test_upsert_spot_db_refreshes_coordinates_and_appends_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "parking.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    await db.init_db()

    first = Spot(
        id="A1",
        lat=47.62319,
        lng=-122.3546,
        status="occupied",
        confidence=0.8,
        updatedAt=datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc),
        cameraId="cam_1",
    )
    second = Spot(
        id="A1",
        lat=47.70000,
        lng=-122.3000,
        status="available",
        confidence=0.92,
        updatedAt=first.updatedAt + timedelta(minutes=5),
        cameraId="cam_2",
    )

    await db.upsert_spot_db(first)
    await db.upsert_spot_db(second)

    async with aiosqlite.connect(db_path) as conn:
        async with conn.execute(
            "SELECT lat, lng, status, confidence, camera_id FROM spots WHERE id = ?",
            ("A1",),
        ) as cursor:
            spot_row = await cursor.fetchone()
        async with conn.execute(
            "SELECT COUNT(*) FROM spot_history WHERE spot_id = ?",
            ("A1",),
        ) as cursor:
            history_count = await cursor.fetchone()

    assert spot_row == (47.7, -122.3, "available", 0.92, "cam_2")
    assert history_count == (2,)
