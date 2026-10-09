"""R0.3: dwell 'soon' promotion tracking, merge composition and demotion."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import db, main
from app.models import Event, Spot, SpotStatus
from app.store import SpotStore

MEAN_DWELL_S = 100.0
THRESHOLD = 0.7
DEMOTE_FACTOR = 1.3


class RecordingHub:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def broadcast(self, event: Event) -> None:
        self.events.append(event)

    @property
    def statuses(self) -> list[str]:
        return [e.payload["status"] for e in self.events]


@pytest.fixture
async def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    merge_path = tmp_path / "merge.json"
    merge_path.write_text(
        json.dumps({"default_priority": ["cam_1", "cam_2"], "per_spot": {}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("MERGE_CONFIG_PATH", str(merge_path))
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "parking.db")
    await db.init_db()
    store = SpotStore()
    hub = RecordingHub()
    monkeypatch.setattr(main, "store", store)
    monkeypatch.setattr(main, "hub", hub)
    return store, hub


def _obs(status: SpotStatus, cam: str | None = "cam_1", spot_id: str = "A1") -> Spot:
    return Spot(
        id=spot_id,
        lat=47.6,
        lng=-122.3,
        status=status,
        confidence=0.9,
        updatedAt=datetime.now(timezone.utc),
        cameraId=cam,
    )


async def _seed_past_sessions(spot_id: str = "A1", count: int = 3) -> None:
    """Completed sessions of exactly MEAN_DWELL_S, a week ago (before any live rows)."""
    t = datetime.now(timezone.utc) - timedelta(days=7)
    for _ in range(count):
        await db.append_spot_history_row(spot_id, "available", 1.0, t)
        t += timedelta(seconds=10)
        await db.append_spot_history_row(spot_id, "occupied", 0.9, t)
        t += timedelta(seconds=MEAN_DWELL_S)
        await db.append_spot_history_row(spot_id, "available", 1.0, t)
        t += timedelta(seconds=60)


async def _occupied_with_history(store: SpotStore, cam: str | None = "cam_1") -> datetime:
    await _seed_past_sessions()
    await store.apply_detector_update(_obs("occupied", cam))
    since = await db.occupied_since_db("A1")
    assert since is not None
    return since


async def _check(since: datetime, fraction: float) -> None:
    await main.dwell_check_once(
        since + timedelta(seconds=fraction * MEAN_DWELL_S),
        threshold=THRESHOLD,
        demote_factor=DEMOTE_FACTOR,
        min_count=3,
    )


async def _published(store: SpotStore, spot_id: str = "A1") -> str:
    spot = await store.get(spot_id)
    assert spot is not None
    return spot.status


# ---------------------------------------------------------------------------
# Acceptance: occupied -> soon -> (car stays) -> occupied
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_promotion_then_demotion_sequence(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)

    await _check(since, 0.5)
    assert await _published(store) == "occupied"
    assert hub.statuses == []

    await _check(since, 0.75)
    assert await _published(store) == "soon"
    assert hub.statuses == ["soon"]

    await _check(since, 1.1)
    assert await _published(store) == "soon"
    assert hub.statuses == ["soon"]

    await _check(since, 1.35)
    assert await _published(store) == "occupied"
    assert hub.statuses == ["soon", "occupied"]

    # The persisted current state follows the published status.
    rows = {r[0]: r for r in await db.load_spots_db()}
    assert rows["A1"][3] == "occupied"


@pytest.mark.anyio
async def test_no_repromotion_after_demotion_in_same_session(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)
    await _check(since, 1.35)
    assert hub.statuses == ["soon", "occupied"]

    for fraction in (1.4, 2.0, 5.0):
        await _check(since, fraction)
    # Same-status observations after the demotion do not bring the promotion back either.
    await store.apply_detector_update(_obs("occupied"))
    await _check(since, 6.0)

    assert await _published(store) == "occupied"
    assert hub.statuses == ["soon", "occupied"]


@pytest.mark.anyio
async def test_past_demote_point_without_bookkeeping_is_not_promoted(env) -> None:
    """A restart loses promotion state; a spot already past the demote point stays red."""
    store, hub = env
    since = await _occupied_with_history(store)

    await _check(since, 1.5)

    assert await _published(store) == "occupied"
    assert hub.statuses == []


# ---------------------------------------------------------------------------
# Acceptance: a new observation no longer reverts an active promotion
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_same_status_observation_keeps_promotion(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)

    changed, published = await store.apply_detector_update(_obs("occupied"))

    assert not changed
    assert published.status == "soon"
    assert await _published(store) == "soon"
    assert hub.statuses == ["soon"]


@pytest.mark.anyio
async def test_other_camera_winning_merge_keeps_promotion(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store, cam="cam_2")
    await _check(since, 0.75)
    assert await _published(store) == "soon"

    # cam_1 has priority and now reports occupied too: base camera switches, status stays.
    changed, published = await store.apply_detector_update(_obs("occupied", cam="cam_1"))

    assert changed  # cameraId changed
    assert published.status == "soon"
    assert published.cameraId == "cam_1"


@pytest.mark.anyio
async def test_legacy_post_without_camera_keeps_promotion(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store, cam=None)
    await _check(since, 0.75)

    changed, published = await store.apply_detector_update(_obs("occupied", cam=None))

    assert not changed
    assert published.status == "soon"


@pytest.mark.anyio
async def test_available_clears_promotion_and_next_session_starts_clean(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)
    await _check(since, 1.35)  # demoted marker set

    changed, published = await store.apply_detector_update(_obs("available"))
    assert changed
    assert published.status == "available"

    changed, published = await store.apply_detector_update(_obs("occupied"))
    assert changed
    assert published.status == "occupied"

    # New session: promotes again once it reaches the threshold.
    new_since = await db.occupied_since_db("A1")
    assert new_since is not None and new_since > since
    await _check(new_since, 0.75)
    assert await _published(store) == "soon"


@pytest.mark.anyio
async def test_available_during_active_promotion_publishes_available(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)

    changed, published = await store.apply_detector_update(_obs("available"))
    assert changed
    assert published.status == "available"

    changed, published = await store.apply_detector_update(_obs("occupied"))
    assert published.status == "occupied"


# ---------------------------------------------------------------------------
# Acceptance: detector motion-soon is unaffected by promotion bookkeeping
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_motion_soon_passes_through_and_is_not_promoted(env) -> None:
    store, hub = env
    await _seed_past_sessions()
    await store.apply_detector_update(_obs("occupied"))
    changed, published = await store.apply_detector_update(_obs("soon"))
    assert changed and published.status == "soon"
    since = await db.occupied_since_db("A1")
    assert since is not None

    await _check(since, 0.75)
    snapshot = {sid: promo for sid, _status, promo in await store.dwell_snapshot()}
    assert snapshot["A1"] is None
    assert hub.statuses == []

    # Motion stops (car settles back): plain occupied, no stale promotion.
    changed, published = await store.apply_detector_update(_obs("occupied"))
    assert changed and published.status == "occupied"


@pytest.mark.anyio
async def test_demotion_while_base_is_motion_soon_publishes_nothing(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)
    assert hub.statuses == ["soon"]

    changed, published = await store.apply_detector_update(_obs("soon"))
    assert not changed and published.status == "soon"

    await _check(since, 1.35)
    assert await _published(store) == "soon"
    assert hub.statuses == ["soon"]

    # Motion stops after the demotion: occupied, and the session is not re-promoted.
    changed, published = await store.apply_detector_update(_obs("occupied"))
    assert changed and published.status == "occupied"
    await _check(since, 1.4)
    assert await _published(store) == "occupied"


# ---------------------------------------------------------------------------
# Writer precedence and other writers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_promote_after_car_left_is_noop(env) -> None:
    """The checker's snapshot said occupied, but the car left before the promotion applied."""
    store, _hub = env
    await _occupied_with_history(store)
    await store.apply_detector_update(_obs("available"))

    result = await store.promote_dwell("A1", datetime.now(timezone.utc))

    assert not result.applied
    assert not result.changed
    assert result.spot is not None and result.spot.status == "available"
    assert await _published(store) == "available"


@pytest.mark.anyio
async def test_promote_and_demote_unknown_spot(env) -> None:
    store, _hub = env
    now = datetime.now(timezone.utc)
    assert not (await store.promote_dwell("nope", now)).applied
    assert not (await store.demote_dwell("nope", now)).applied


@pytest.mark.anyio
async def test_promotion_keeps_latest_base_fields(env) -> None:
    """Promotion composes with the current base instead of an older snapshot."""
    store, _hub = env
    since = await _occupied_with_history(store)
    moved = _obs("occupied").model_copy(update={"lat": 47.7, "confidence": 0.5})
    await store.apply_detector_update(moved)

    await _check(since, 0.75)

    spot = await store.get("A1")
    assert spot is not None
    assert (spot.status, spot.lat, spot.confidence) == ("soon", 47.7, 0.5)


@pytest.mark.anyio
async def test_upsert_canonical_clears_promotion(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store)
    await _check(since, 0.75)

    await store.upsert_canonical(_obs("occupied", cam=None))
    assert await _published(store) == "occupied"
    snapshot = {sid: promo for sid, _status, promo in await store.dwell_snapshot()}
    assert snapshot["A1"] is None


@pytest.mark.anyio
async def test_promoted_updated_at_does_not_go_backwards(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store)
    promote_at = since + timedelta(seconds=0.75 * MEAN_DWELL_S)
    await _check(since, 0.75)
    spot = await store.get("A1")
    assert spot is not None and spot.updatedAt >= promote_at

    # Observation carrying an older timestamp (naive, as some clients send) keeps soon.
    old = _obs("occupied").model_copy(update={"updatedAt": datetime(2026, 1, 1)})
    _changed, published = await store.apply_detector_update(old)
    assert published.status == "soon"
    assert published.updatedAt >= promote_at


@pytest.mark.anyio
async def test_concurrent_writers_keep_history_in_order(env) -> None:
    """Checker promotion racing a departure never leaves 'soon' after 'available'."""
    store, _hub = env
    since = await _occupied_with_history(store)

    await asyncio.gather(
        _check(since, 0.75),
        store.apply_detector_update(_obs("available")),
    )

    final = await _published(store)
    rows = {r[0]: r for r in await db.load_spots_db()}
    assert rows["A1"][3] == final
    assert final == "available"
    assert await db.occupied_since_db("A1") is None


@pytest.mark.anyio
async def test_dwell_stats_unchanged_by_promotion_rows(env) -> None:
    store, _hub = env
    since = await _occupied_with_history(store)
    before = await db.query_dwell_db("A1")

    await _check(since, 0.75)
    await _check(since, 1.35)
    await store.apply_detector_update(_obs("available"))

    after = await db.query_dwell_db("A1")
    assert after["count"] == before["count"] + 1
    assert before["mean"] == MEAN_DWELL_S
    # The promotion/demotion rows did not split the live session in two.
    assert await db.occupied_since_db("A1") is None


@pytest.mark.anyio
async def test_insufficient_history_never_promotes(env) -> None:
    store, hub = env
    await _seed_past_sessions(count=2)
    await store.apply_detector_update(_obs("occupied"))
    since = await db.occupied_since_db("A1")
    assert since is not None

    await _check(since, 0.75)

    assert await _published(store) == "occupied"
    assert hub.statuses == []


# ---------------------------------------------------------------------------
# Configuration, loop resilience, logging
# ---------------------------------------------------------------------------


def test_soon_demote_factor_parsing(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    monkeypatch.delenv("SOON_DEMOTE_FACTOR", raising=False)
    assert main.soon_demote_factor() == 1.3

    monkeypatch.setenv("SOON_DEMOTE_FACTOR", "1.5")
    assert main.soon_demote_factor() == 1.5

    for bad in ("abc", "0", "-1", "nan", "inf"):
        monkeypatch.setenv("SOON_DEMOTE_FACTOR", bad)
        with caplog.at_level(logging.WARNING, logger="app.main"):
            caplog.clear()
            assert main.soon_demote_factor() == 1.3
        assert "Invalid SOON_DEMOTE_FACTOR" in caplog.text


@pytest.mark.anyio
async def test_demote_factor_not_above_threshold_never_promotes(env) -> None:
    store, hub = env
    since = await _occupied_with_history(store)

    for fraction in (0.75, 1.0, 2.0):
        await main.dwell_check_once(
            since + timedelta(seconds=fraction * MEAN_DWELL_S),
            threshold=THRESHOLD,
            demote_factor=THRESHOLD,
            min_count=3,
        )

    assert await _published(store) == "occupied"
    assert hub.statuses == []


@pytest.mark.anyio
async def test_dwell_checker_loop_survives_failing_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    async def flaky_pass() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        if calls >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(main, "_DWELL_CHECK_INTERVAL", 0)
    monkeypatch.setattr(main, "dwell_check_once", flaky_pass)

    with pytest.raises(asyncio.CancelledError):
        await main.dwell_checker_loop()
    assert calls == 3


@pytest.mark.anyio
async def test_promotion_and_demotion_are_logged(env, caplog) -> None:
    store, _hub = env
    since = await _occupied_with_history(store)

    with caplog.at_level(logging.INFO, logger="app.main"):
        await _check(since, 0.75)
        await _check(since, 1.35)

    assert "spot A1 promoted to soon" in caplog.text
    assert "spot A1 demoted, prediction missed" in caplog.text


def _bare_logging(monkeypatch: pytest.MonkeyPatch) -> logging.Logger:
    """Simulate plain uvicorn: no handlers on the root or ``app`` logger.

    Called inside the test body: pytest attaches its capture handlers to the root
    logger after fixtures run.
    """
    root = logging.getLogger()
    app_logger = logging.getLogger("app")
    monkeypatch.setattr(root, "handlers", [])
    monkeypatch.setattr(app_logger, "handlers", [])
    monkeypatch.setattr(app_logger, "level", logging.NOTSET)
    return app_logger


def test_app_logging_configured_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PARKINGSPOTTER_LOG_LEVEL", raising=False)
    app_logger = _bare_logging(monkeypatch)
    main._configure_app_logging()
    assert len(app_logger.handlers) == 1
    assert app_logger.level == logging.INFO

    # Idempotent: a second create_app() does not add a second handler.
    main._configure_app_logging()
    assert len(app_logger.handlers) == 1


def test_app_log_level_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_LOG_LEVEL", "warning")
    app_logger = _bare_logging(monkeypatch)
    main._configure_app_logging()
    assert app_logger.level == logging.WARNING


def test_app_log_level_invalid_falls_back_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARKINGSPOTTER_LOG_LEVEL", "chatty")
    app_logger = _bare_logging(monkeypatch)
    main._configure_app_logging()
    assert app_logger.level == logging.INFO


def test_app_logging_left_alone_when_root_configured(monkeypatch) -> None:
    root = logging.getLogger()
    app_logger = logging.getLogger("app")
    monkeypatch.setattr(root, "handlers", [logging.NullHandler()])
    monkeypatch.setattr(app_logger, "handlers", [])
    main._configure_app_logging()
    assert app_logger.handlers == []
