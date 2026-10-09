from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.hub import Hub
from app.models import Spot
from app.store import SpotStore

APP_DIR = Path(__file__).resolve().parents[1] / "app"

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
RETENTION_DAYS = 90
CUTOFF = NOW - timedelta(days=RETENTION_DAYS)


@pytest.fixture
async def db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "parking.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    await db.init_db()
    return path


async def _rows(spot_id: str, statuses: list[tuple[str, datetime]]) -> None:
    for status, recorded_at in statuses:
        await db.append_spot_history_row(spot_id, status, 0.9, recorded_at)


async def _session(spot_id: str, start: datetime, duration: timedelta) -> None:
    await _rows(spot_id, [("occupied", start), ("available", start + duration)])


def _history(path: Path, spot_id: str) -> list[tuple[str, str]]:
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT status, recorded_at FROM spot_history WHERE spot_id = ? "
            "ORDER BY recorded_at ASC",
            (spot_id,),
        ).fetchall()


# -----------------------------
# Connection helper: WAL + busy_timeout
# -----------------------------


@pytest.mark.anyio
async def test_init_db_switches_database_to_wal(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        (mode,) = conn.execute("PRAGMA journal_mode").fetchone()

    assert mode == "wal"


@pytest.mark.anyio
async def test_helper_connections_set_busy_timeout(db_path: Path) -> None:
    async with db.connect() as conn:
        async with conn.execute("PRAGMA busy_timeout") as cursor:
            (timeout_ms,) = await cursor.fetchone()

    assert timeout_ms == db.BUSY_TIMEOUT_MS == 5000


def test_only_the_helper_opens_sqlite_connections() -> None:
    sources = {path.name: path.read_text(encoding="utf-8") for path in APP_DIR.glob("*.py")}

    opens = {name: src.count("aiosqlite.connect(") for name, src in sources.items()}
    assert {name: n for name, n in opens.items() if n} == {"db.py": 1}
    assert not [name for name, src in sources.items() if "sqlite3.connect(" in src]
    # Every database function in db.py goes through connect().
    assert sources["db.py"].count("async with connect() as db:") >= 9


@pytest.mark.anyio
async def test_reader_is_not_blocked_by_an_exclusive_writer(db_path: Path) -> None:
    await _session("A1", NOW - timedelta(hours=2), timedelta(minutes=10))

    writer = sqlite3.connect(db_path, isolation_level=None)
    try:
        writer.execute("BEGIN EXCLUSIVE")
        writer.execute(
            "INSERT INTO spot_history (spot_id, status, confidence, recorded_at) "
            "VALUES ('A1', 'occupied', 0.9, ?)",
            (NOW.isoformat(),),
        )
        # Rollback-journal mode would wait out busy_timeout and then raise
        # "database is locked"; WAL readers see the last committed snapshot at once.
        dwell = await asyncio.wait_for(db.query_dwell_db("A1"), timeout=2.0)
    finally:
        writer.execute("ROLLBACK")
        writer.close()

    assert dwell == {"count": 1, "mean": 600.0, "stddev": 0.0}


@pytest.mark.anyio
async def test_writer_waits_for_a_briefly_held_lock(db_path: Path) -> None:
    holder = sqlite3.connect(db_path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    asyncio.get_running_loop().call_later(0.3, holder.execute, "COMMIT")
    started = time.monotonic()
    try:
        await db.upsert_spot_db(
            Spot(id="A1", lat=47.6, lng=-122.3, status="occupied", cameraId="cam_1")
        )
    finally:
        holder.close()

    assert time.monotonic() - started >= 0.2
    assert [status for status, _ in _history(db_path, "A1")] == ["occupied"]


# -----------------------------
# History retention
# -----------------------------


@pytest.mark.anyio
async def test_prune_removes_completed_sessions_older_than_cutoff(db_path: Path) -> None:
    await _session("A1", NOW - timedelta(days=200), timedelta(minutes=10))
    await _session("A1", NOW - timedelta(days=150), timedelta(minutes=20))
    await _session("A1", NOW - timedelta(days=10), timedelta(minutes=30))
    assert (await db.query_dwell_db("A1"))["count"] == 3

    deleted = await db.prune_history_db(RETENTION_DAYS, now=NOW)

    assert deleted == 3
    rows = _history(db_path, "A1")
    # Only the old session's closing "available" row survives the cutoff; it is a
    # no-op for dwell parsing.
    assert [status for status, _ in rows] == ["available", "occupied", "available"]
    assert await db.query_dwell_db("A1") == {"count": 1, "mean": 1800.0, "stddev": 0.0}


@pytest.mark.anyio
async def test_prune_keeps_a_session_that_straddles_the_cutoff(db_path: Path) -> None:
    await _session("B1", NOW - timedelta(days=200), timedelta(minutes=10))
    await _rows(
        "B1",
        [
            ("occupied", CUTOFF - timedelta(hours=2)),
            ("soon", CUTOFF - timedelta(hours=1)),
            ("available", CUTOFF + timedelta(hours=1)),
        ],
    )

    deleted = await db.prune_history_db(RETENTION_DAYS, now=NOW)

    assert deleted == 1  # the 200-day-old "occupied" row
    statuses = [status for status, _ in _history(db_path, "B1")]
    assert statuses == ["available", "occupied", "soon", "available"]
    assert await db.query_dwell_db("B1") == {"count": 1, "mean": 10800.0, "stddev": 0.0}


@pytest.mark.anyio
async def test_prune_never_touches_an_open_session(db_path: Path) -> None:
    session_start = NOW - timedelta(days=200)
    await _rows(
        "C1",
        [
            ("available", NOW - timedelta(days=300)),
            ("occupied", session_start),
            ("soon", NOW - timedelta(days=120)),
        ],
    )
    # No "available" before the cutoff at all: nothing can be closed, nothing goes.
    await _rows("C2", [("occupied", NOW - timedelta(days=400))])
    before_c1 = _history(db_path, "C1")

    deleted = await db.prune_history_db(RETENTION_DAYS, now=NOW)

    assert deleted == 0
    assert _history(db_path, "C1") == before_c1
    assert len(_history(db_path, "C2")) == 1
    assert await db.occupied_since_db("C1") == session_start


@pytest.mark.anyio
async def test_dwell_stats_inside_window_are_unchanged_and_prune_is_idempotent(
    db_path: Path,
) -> None:
    # Window-only spot: every session ended after the cutoff.
    await _session("D1", NOW - timedelta(days=30), timedelta(minutes=5))
    await _session("D1", NOW - timedelta(days=20), timedelta(minutes=7))
    await _session("D1", NOW - timedelta(days=1), timedelta(minutes=9))
    # Mixed spot: old sessions plus the same three in-window sessions.
    await _session("D2", NOW - timedelta(days=365), timedelta(hours=5))
    await _session("D2", NOW - timedelta(days=120), timedelta(hours=3))
    await _session("D2", NOW - timedelta(days=30), timedelta(minutes=5))
    await _session("D2", NOW - timedelta(days=20), timedelta(minutes=7))
    await _session("D2", NOW - timedelta(days=1), timedelta(minutes=9))
    window_stats = await db.query_dwell_db("D1")
    d1_rows = _history(db_path, "D1")

    first = await db.prune_history_db(RETENTION_DAYS, now=NOW)
    second = await db.prune_history_db(RETENTION_DAYS, now=NOW)

    assert first == 3
    assert second == 0
    assert _history(db_path, "D1") == d1_rows
    assert await db.query_dwell_db("D1") == window_stats
    assert await db.query_dwell_db("D2") == window_stats
    assert window_stats["count"] == 3


@pytest.mark.anyio
@pytest.mark.parametrize("days", [0, -1])
async def test_prune_with_retention_disabled_deletes_nothing(db_path: Path, days: int) -> None:
    await _session("E1", NOW - timedelta(days=1000), timedelta(minutes=10))
    await _session("E1", NOW - timedelta(days=900), timedelta(minutes=10))

    assert await db.prune_history_db(days, now=NOW) == 0
    assert len(_history(db_path, "E1")) == 4


@pytest.mark.parametrize(
    ("raw", "expected", "warns"),
    [
        (None, 90, False),
        ("", 90, False),
        ("30", 30, False),
        (" 7 ", 7, False),
        ("0", 0, False),
        ("-5", 90, True),
        ("ninety", 90, True),
        ("1.5", 90, True),
        ("36500", 36500, False),
        ("9999999", 36500, True),
    ],
)
def test_history_retention_days_env(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raw: str | None,
    expected: int,
    warns: bool,
) -> None:
    if raw is None:
        monkeypatch.delenv(db.HISTORY_RETENTION_ENV, raising=False)
    else:
        monkeypatch.setenv(db.HISTORY_RETENTION_ENV, raw)

    with caplog.at_level(logging.WARNING, logger="app.db"):
        assert db.history_retention_days() == expected

    assert (db.HISTORY_RETENTION_ENV in caplog.text) is warns


# -----------------------------
# Wiring: startup pass and daily loop
# -----------------------------


def _start_app(monkeypatch: pytest.MonkeyPatch, db_file: Path) -> TestClient:
    monkeypatch.setattr(db, "DB_PATH", db_file)
    monkeypatch.setenv("SIMULATOR", "false")
    monkeypatch.setattr(main, "store", SpotStore())
    monkeypatch.setattr(main, "hub", Hub())
    monkeypatch.setattr(main, "dwell_checker_loop", lambda: _noop())
    return TestClient(main.create_app())


async def _noop() -> None:
    return None


def _seed_old_and_recent_history(db_file: Path) -> None:
    now = datetime.now(timezone.utc)

    async def seed() -> None:
        await db.init_db()
        # Not a demo seed id, so startup seeding adds no rows for it.
        await _session("Z9", now - timedelta(days=200), timedelta(minutes=10))
        await _session("Z9", now - timedelta(days=2), timedelta(minutes=10))

    asyncio.run(seed())


@pytest.mark.parametrize(("retention", "rows_left"), [("90", 3), ("0", 4)])
def test_startup_runs_one_retention_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retention: str,
    rows_left: int,
) -> None:
    db_file = tmp_path / "startup.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    _seed_old_and_recent_history(db_file)
    monkeypatch.setenv(db.HISTORY_RETENTION_ENV, retention)

    with _start_app(monkeypatch, db_file) as client:
        assert client.get("/health").status_code == 200
        assert len(_history(db_file, "Z9")) == rows_left


def test_startup_survives_a_failing_retention_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def boom(_days: int) -> int:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(main, "prune_history_db", boom)

    with _start_app(monkeypatch, tmp_path / "boom.db") as client:
        assert client.get("/health").status_code == 200


@pytest.mark.anyio
async def test_retention_loop_keeps_running_after_a_failed_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []
    done = asyncio.Event()

    async def flaky(days: int) -> int:
        calls.append(days)
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        if len(calls) >= 3:
            done.set()
        return 0

    monkeypatch.setattr(main, "prune_history_db", flaky)
    monkeypatch.setattr(main, "_HISTORY_RETENTION_INTERVAL_SECONDS", 0)

    task = asyncio.create_task(main.history_retention_loop(30))
    try:
        await asyncio.wait_for(done.wait(), timeout=2.0)
    finally:
        task.cancel()

    assert calls[:3] == [30, 30, 30]
