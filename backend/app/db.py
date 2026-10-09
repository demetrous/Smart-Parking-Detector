from __future__ import annotations

import logging
import os
import statistics
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite

log = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", "parking.db"))
_ACTIVE_SESSION_STATUSES = {"occupied", "soon"}

# Per-connection wait for a competing lock before SQLite raises "database is locked".
BUSY_TIMEOUT_MS = 5000

HISTORY_RETENTION_ENV = "PARKINGSPOTTER_HISTORY_RETENTION_DAYS"
DEFAULT_HISTORY_RETENTION_DAYS = 90

# Databases already switched to WAL in this process. journal_mode=WAL is stored in
# the database file, so it only needs setting once per path (single-process backend).
_wal_checked: set[str] = set()

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

_INDEX_HISTORY_SPOT_TIME = """
CREATE INDEX IF NOT EXISTS idx_spot_history_spot_id_time
ON spot_history (spot_id, recorded_at)
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


def _db_key(path: Path | str) -> str:
    raw = str(path)
    if raw == ":memory:" or raw.startswith("file:"):
        return raw
    return str(Path(raw).resolve())


@asynccontextmanager
async def connect() -> AsyncIterator[aiosqlite.Connection]:
    """Open a connection to ``DB_PATH``. Every database operation goes through here.

    Sets ``busy_timeout`` on each connection and switches the database to WAL the
    first time this process opens it, so readers never block on the detector's
    writes and short write overlaps wait instead of failing.
    """
    path = DB_PATH
    async with aiosqlite.connect(path) as db:
        await db.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        key = _db_key(path)
        if key not in _wal_checked:
            async with db.execute("PRAGMA journal_mode=WAL") as cursor:
                row = await cursor.fetchone()
            mode = str(row[0]).lower() if row else "unknown"
            if mode != "wal":
                log.warning(
                    "SQLite at %s is in journal_mode=%s, not WAL; readers may block on writes",
                    path,
                    mode,
                )
            _wal_checked.add(key)
        yield db


async def init_db() -> None:
    async with connect() as db:
        await db.execute(_CREATE_SPOTS)
        await db.execute(_CREATE_HISTORY)
        await db.execute(_CREATE_OBSERVATIONS)
        await db.execute(_INDEX_HISTORY_SPOT_TIME)
        await db.commit()


async def append_spot_history_row(
    spot_id: str,
    status: str,
    confidence: float,
    recorded_at: datetime,
) -> None:
    """Append one row to spot_history without updating the spots table (dev tooling)."""
    async with connect() as db:
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


async def upsert_spot_db(
    spot,
    *,
    history_recorded_at: datetime | None = None,
) -> None:  # type: ignore[no-untyped-def]
    """Persist current state and append a history record.

    By default, ``recorded_at`` for ``spot_history`` is wall-clock now so the event
    log stays chronologically ordered even when merged observations carry older
    ``updatedAt``. Tests may pass *history_recorded_at* explicitly.
    """
    history_at = history_recorded_at or datetime.now(timezone.utc)
    async with connect() as db:
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
            (spot.id, spot.status, spot.confidence, history_at.isoformat()),
        )
        await db.commit()


async def load_spots_db() -> list[tuple]:
    """Return all persisted spots on startup."""
    try:
        async with connect() as db:
            async with db.execute(
                "SELECT id, lat, lng, status, confidence, camera_id, updated_at FROM spots"
            ) as cursor:
                return await cursor.fetchall()
    except Exception:
        log.exception("Failed to load spots from %s", DB_PATH)
        raise


async def upsert_observation_db(spot) -> None:  # type: ignore[no-untyped-def]
    """Persist one camera's view of a spot (multi-camera ingest)."""
    if not spot.cameraId:
        return
    async with connect() as db:
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
        async with connect() as db:
            async with db.execute(
                "SELECT spot_id, camera_id, lat, lng, status, confidence, updated_at "
                "FROM spot_observations"
            ) as cursor:
                return await cursor.fetchall()
    except Exception:
        log.exception("Failed to load spot_observations from %s", DB_PATH)
        raise


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
    async with connect() as db:
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
    async with connect() as db:
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


def history_retention_days() -> int:
    """Return the configured ``spot_history`` retention in days (``0`` = keep forever)."""
    raw = os.getenv(HISTORY_RETENTION_ENV, "").strip()
    if not raw:
        return DEFAULT_HISTORY_RETENTION_DAYS
    try:
        days = int(raw)
    except ValueError:
        days = -1
    if days < 0:
        log.warning(
            "Ignoring invalid %s=%r; using %d days",
            HISTORY_RETENTION_ENV,
            raw,
            DEFAULT_HISTORY_RETENTION_DAYS,
        )
        return DEFAULT_HISTORY_RETENTION_DAYS
    return days


async def prune_history_db(retention_days: int, *, now: datetime | None = None) -> int:
    """Delete ``spot_history`` sessions that ended more than *retention_days* ago.

    Works on whole dwell sessions so dwell stats inside the window are unchanged:
    for each spot, rows strictly older than its latest ``available`` row before the
    cutoff are deleted. Everything they belonged to closed before the cutoff. A
    session that straddles the cutoff, and the spot's current open session, are
    kept in full however old they are. Each spot is pruned in its own short write
    transaction so ingest is never locked out for long.

    Returns the number of rows deleted. ``retention_days <= 0`` deletes nothing.
    """
    if retention_days <= 0:
        return 0
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = (current - timedelta(days=retention_days)).astimezone(timezone.utc).isoformat()

    deleted = 0
    async with connect() as db:
        async with db.execute(
            "SELECT DISTINCT spot_id FROM spot_history WHERE recorded_at < ?",
            (cutoff,),
        ) as cursor:
            spot_ids = [row[0] for row in await cursor.fetchall()]

        for spot_id in spot_ids:
            await db.execute("BEGIN IMMEDIATE")
            try:
                async with db.execute(
                    "SELECT MAX(recorded_at) FROM spot_history "
                    "WHERE spot_id = ? AND status = 'available' AND recorded_at < ?",
                    (spot_id, cutoff),
                ) as cursor:
                    row = await cursor.fetchone()
                boundary = row[0] if row else None
                if boundary is not None:
                    cursor = await db.execute(
                        "DELETE FROM spot_history WHERE spot_id = ? AND recorded_at < ?",
                        (spot_id, boundary),
                    )
                    deleted += max(cursor.rowcount, 0)
                await db.commit()
            except BaseException:
                await db.rollback()
                raise
    return deleted
