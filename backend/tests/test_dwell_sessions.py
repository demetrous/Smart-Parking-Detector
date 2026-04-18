from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db
from app.models import Spot


async def _write_spot_history(
    tmp_db_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    statuses: list[tuple[str, datetime]],
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_db_path)
    await db.init_db()
    for status, updated_at in statuses:
        await db.upsert_spot_db(
            Spot(
                id="A1",
                lat=47.62319,
                lng=-122.3546,
                status=status,
                confidence=0.9,
                updatedAt=updated_at,
                cameraId="cam_1",
            )
        )


@pytest.mark.anyio
async def test_dwell_stats_treat_occupied_and_soon_as_one_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    await _write_spot_history(
        tmp_path / "parking.db",
        monkeypatch,
        [
            ("occupied", base),
            ("soon", base + timedelta(minutes=5)),
            ("occupied", base + timedelta(minutes=8)),
            ("available", base + timedelta(minutes=12)),
        ],
    )

    dwell = await db.query_dwell_db("A1")
    occupied_since = await db.occupied_since_db("A1")

    assert dwell == {"count": 1, "mean": 720.0, "stddev": 0.0}
    assert occupied_since is None


@pytest.mark.anyio
async def test_occupied_since_uses_first_transition_into_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = datetime(2026, 4, 18, 12, 0, tzinfo=timezone.utc)
    await _write_spot_history(
        tmp_path / "parking.db",
        monkeypatch,
        [
            ("available", base),
            ("soon", base + timedelta(minutes=1)),
            ("occupied", base + timedelta(minutes=3)),
        ],
    )

    occupied_since = await db.occupied_since_db("A1")

    assert occupied_since == base + timedelta(minutes=1)


@pytest.mark.anyio
async def test_dwell_helpers_return_safe_empty_results_with_no_completed_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()

    dwell = await db.query_dwell_db("A1")
    occupied_since = await db.occupied_since_db("A1")

    assert dwell == {"count": 0, "mean": None, "stddev": None}
    assert occupied_since is None
