from __future__ import annotations

import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

DB_PATH = Path(os.getenv("DB_PATH", "parking.db"))

_CREATE_SPOTS = """
CREATE TABLE IF NOT EXISTS spots (
    id          TEXT PRIMARY KEY,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    status      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    camera_id   TEXT,
    updated_at  TEXT NOT NULL
)
"""

_CREATE_HISTORY = """
CREATE TABLE IF NOT EXISTS spot_history (
    rowid       INTEGER PRIMARY KEY AUTOINCREMENT,
    spot_id     TEXT NOT NULL,
    status      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    recorded_at TEXT NOT NULL
)
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_SPOTS)
        await db.execute(_CREATE_HISTORY)
        await db.commit()


async def upsert_spot_db(spot) -> None:  # type: ignore[no-untyped-def]
    """Persist current state and append a history record."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO spots (id, lat, lng, status, confidence, camera_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status      = excluded.status,
                confidence  = excluded.confidence,
                camera_id   = excluded.camera_id,
                updated_at  = excluded.updated_at
            """,
            (
                spot.id,
                spot.lat,
                spot.lng,
                spot.status,
                spot.confidence,
                spot.cameraId,
                spot.updatedAt.isoformat(),
            ),
        )
        await db.execute(
            """
            INSERT INTO spot_history (spot_id, status, confidence, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (spot.id, spot.status, spot.confidence, spot.updatedAt.isoformat()),
        )
        await db.commit()


async def load_spots_db() -> list[tuple]:
    """Return all persisted spots on startup."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT id, lat, lng, status, confidence, camera_id, updated_at FROM spots"
            ) as cursor:
                return await cursor.fetchall()
    except Exception:
        return []


async def query_dwell_db(spot_id: str) -> dict:
    """Return dwell-time statistics (seconds) for a spot.

    A "dwell" is the duration between a spot transitioning *into* occupied/soon
    and the next transition *out* of those states (back to available).
    Returns {"count": int, "mean": float | None, "stddev": float | None}.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status, recorded_at FROM spot_history "
            "WHERE spot_id = ? ORDER BY recorded_at ASC",
            (spot_id,),
        ) as cursor:
            rows = await cursor.fetchall()

    dwells: list[float] = []
    occupied_start: datetime | None = None
    for status, recorded_at in rows:
        if status in ("occupied", "soon") and occupied_start is None:
            occupied_start = datetime.fromisoformat(recorded_at)
        elif status == "available" and occupied_start is not None:
            end = datetime.fromisoformat(recorded_at)
            dwells.append((end - occupied_start).total_seconds())
            occupied_start = None

    if not dwells:
        return {"count": 0, "mean": None, "stddev": None}
    mean = statistics.mean(dwells)
    stddev = statistics.stdev(dwells) if len(dwells) > 1 else 0.0
    return {"count": len(dwells), "mean": round(mean, 2), "stddev": round(stddev, 2)}


async def occupied_since_db(spot_id: str) -> datetime | None:
    """Return when the spot most recently transitioned to 'occupied'."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT recorded_at FROM spot_history "
            "WHERE spot_id = ? AND status = 'occupied' "
            "ORDER BY recorded_at DESC LIMIT 1",
            (spot_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    ts = datetime.fromisoformat(row[0])
    # Ensure timezone-aware so arithmetic with utcnow() works
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts
