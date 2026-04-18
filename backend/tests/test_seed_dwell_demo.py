from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import db
from app.models import Spot


@pytest.mark.anyio
async def test_seed_dwell_demo_sparse_adds_completed_sessions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()
    await db.upsert_spot_db(
        Spot(
            id="A1",
            lat=47.0,
            lng=-122.0,
            status="occupied",
            confidence=0.9,
            updatedAt=datetime.now(timezone.utc),
            cameraId=None,
        )
    )
    before = await db.query_dwell_db("A1")
    assert before["count"] == 0

    await db.seed_dwell_demo_sparse(["A1"], min_completed_sessions=3)
    after = await db.query_dwell_db("A1")
    assert after["count"] >= 3
    assert after["mean"] is not None


@pytest.mark.anyio
async def test_seed_dwell_demo_sparse_is_idempotent_when_satisfied(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()
    await db.upsert_spot_db(
        Spot(
            id="A1",
            lat=47.0,
            lng=-122.0,
            status="available",
            confidence=1.0,
            updatedAt=datetime.now(timezone.utc),
            cameraId=None,
        )
    )
    await db.seed_dwell_demo_sparse(["A1"], min_completed_sessions=2)
    first = await db.query_dwell_db("A1")
    await db.seed_dwell_demo_sparse(["A1"], min_completed_sessions=2)
    second = await db.query_dwell_db("A1")
    assert first["count"] == second["count"]
