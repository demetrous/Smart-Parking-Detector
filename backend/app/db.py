from __future__ import annotations

import os
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite

DB_PATH = Path(os.getenv("DB_PATH", "parking.db"))
_ACTIVE_SESSION_STATUSES = {"occupied", "soon"}

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

_CREATE_OBSERVATIONS = """
CREATE TABLE IF NOT EXISTS spot_observations (
    spot_id     TEXT NOT NULL,
    camera_id   TEXT NOT NULL,
    lat         REAL NOT NULL,
    lng         REAL NOT NULL,
    status      TEXT NOT NULL,
    confidence  REAL NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (spot_id, camera_id)
)
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(_CREATE_SPOTS)
        await db.execute(_CREATE_HISTORY)
        await db.execute(_CREATE_OBSERVATIONS)
        await db.commit()


async def append_spot_history_row(
    spot_id: str,
    status: str,
    confidence: float,
    recorded_at: datetime,
) -> None:
    """Append one row to spot_history without updating the spots table (dev tooling)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO spot_history (spot_id, status, confidence, recorded_at)
            VALUES (?, ?, ?, ?)
            """,
            (spot_id, status, confidence, recorded_at.isoformat()),
        )
        await db.commit()


async def seed_dwell_demo_sparse(spot_ids: list[str], min_completed_sessions: int) -> None:
    """Append synthetic *past* completed occupancy sessions so dwell stats populate quickly.

    Only adds sessions for spots whose completed-dwell count is below *min_completed_sessions*.
    Timestamps are several days in the past so they sort before rows written at startup.
    """
    if min_completed_sessions <= 0:
        return
    anchor = datetime.now(timezone.utc) - timedelta(days=7)
    dwell_seconds = (400.0, 520.0, 440.0, 610.0, 480.0)
    for spot_id in spot_ids:
        info = await query_dwell_db(spot_id)
        need = min_completed_sessions - info["count"]
        if need <= 0:
            continue
        t = anchor
        for i in range(need):
            duration = dwell_seconds[i % len(dwell_seconds)]
            await append_spot_history_row(spot_id, "available", 1.0, t)
            t += timedelta(seconds=45)
            await append_spot_history_row(spot_id, "occupied", 0.92, t)
            t += timedelta(seconds=duration)
            await append_spot_history_row(spot_id, "available", 1.0, t)
            t += timedelta(minutes=2)


async def upsert_spot_db(spot) -> None:  # type: ignore[no-untyped-def]
    """Persist current state and append a history record."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO spots (id, lat, lng, status, confidence, camera_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                lat         = excluded.lat,
                lng         = excluded.lng,
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


async def upsert_observation_db(spot) -> None:  # type: ignore[no-untyped-def]
    """Persist one camera's view of a spot (multi-camera ingest)."""
    if not spot.cameraId:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO spot_observations (spot_id, camera_id, lat, lng, status, confidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(spot_id, camera_id) DO UPDATE SET
                lat         = excluded.lat,
                lng         = excluded.lng,
                status      = excluded.status,
                confidence  = excluded.confidence,
                updated_at  = excluded.updated_at
            """,
            (
                spot.id,
                spot.cameraId,
                spot.lat,
                spot.lng,
                spot.status,
                spot.confidence,
                spot.updatedAt.isoformat(),
            ),
        )
        await db.commit()


async def load_observations_db() -> list[tuple]:
    """Return all per-camera observations."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                "SELECT spot_id, camera_id, lat, lng, status, confidence, updated_at "
                "FROM spot_observations"
            ) as cursor:
                return await cursor.fetchall()
    except Exception:
        return []


def _parse_recorded_at(raw: str) -> datetime:
    ts = datetime.fromisoformat(raw)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _occupancy_sessions(rows: Iterable[tuple[str, str]]) -> list[tuple[datetime, datetime | None]]:
    """Return normalized occupancy sessions from a spot's history rows."""
    sessions: list[tuple[datetime, datetime | None]] = []
    current_start: datetime | None = None

    for status, recorded_at in rows:
        ts = _parse_recorded_at(recorded_at)
        if status in _ACTIVE_SESSION_STATUSES:
            if current_start is None:
                current_start = ts
            continue

        if status == "available" and current_start is not None:
            sessions.append((current_start, ts))
            current_start = None

    if current_start is not None:
        sessions.append((current_start, None))

    return sessions


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
    for start, end in _occupancy_sessions(rows):
        if end is not None:
            dwells.append((end - start).total_seconds())

    if not dwells:
        return {"count": 0, "mean": None, "stddev": None}
    mean = statistics.mean(dwells)
    stddev = statistics.stdev(dwells) if len(dwells) > 1 else 0.0
    return {"count": len(dwells), "mean": round(mean, 2), "stddev": round(stddev, 2)}


async def occupied_since_db(spot_id: str) -> datetime | None:
    """Return when the current occupied/soon session started, if any."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status, recorded_at FROM spot_history "
            "WHERE spot_id = ? ORDER BY recorded_at ASC",
            (spot_id,),
        ) as cursor:
            rows = await cursor.fetchall()

    sessions = _occupancy_sessions(rows)
    if not sessions:
        return None

    start, end = sessions[-1]
    return start if end is None else None
