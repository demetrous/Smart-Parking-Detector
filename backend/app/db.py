from __future__ import annotations

import os
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
