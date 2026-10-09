from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

from .db import current_session_statuses_db, upsert_observation_db, upsert_spot_db
from .merge import MergeConfig, merge_canonical_for_spot, merge_config_path
from .models import Spot, SpotStatus

log = logging.getLogger(__name__)


def _canonical_fields_differ(a: Spot, b: Spot) -> bool:
    return (
        a.status != b.status
        or a.lat != b.lat
        or a.lng != b.lng
        or a.confidence != b.confidence
        or a.cameraId != b.cameraId
    )


def _spot_from_spots_row(row: tuple) -> Spot:
    ts = datetime.fromisoformat(row[6])
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return Spot(
        id=row[0],
        lat=row[1],
        lng=row[2],
        status=row[3],
        confidence=row[4],
        cameraId=row[5],
        updatedAt=ts,
    )


def _aware(ts: datetime) -> datetime:
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


@dataclass(frozen=True)
class DwellPromotion:
    """Dwell-time 'soon' bookkeeping for one occupancy session of one spot.

    Active while ``demoted_at`` is None. A demoted promotion stays recorded until the
    session ends (base goes ``available``) so the checker does not promote again.
    """

    promoted_at: datetime
    demoted_at: datetime | None = None

    @property
    def active(self) -> bool:
        return self.demoted_at is None


class DwellCandidate(NamedTuple):
    """One row of ``dwell_snapshot``."""

    spot_id: str
    base_status: SpotStatus
    promotion: DwellPromotion | None
    #: Occupancy-session counter; pass it back to ``promote_dwell`` / ``demote_dwell``.
    session: int


class DwellChange(NamedTuple):
    """Result of ``promote_dwell`` / ``demote_dwell``."""

    #: Bookkeeping was updated (False: no-op because the state no longer qualified).
    applied: bool
    #: The published spot changed and should be broadcast.
    changed: bool
    #: The published spot after the call (None if the spot is unknown).
    spot: Spot | None


def _compose(base: Spot, promotion: DwellPromotion | None) -> Spot:
    """Published spot from base canonical + dwell promotion.

    Base ``occupied`` + active promotion -> ``soon``. Every other combination publishes
    the base status, so detector motion ``soon`` and ``available`` pass through as-is.
    ``updatedAt`` never moves backwards across a promotion or demotion.
    """
    if promotion is None or base.status != "occupied":
        return base
    if promotion.active:
        return base.model_copy(
            update={
                "status": "soon",
                "updatedAt": max(_aware(base.updatedAt), promotion.promoted_at),
            }
        )
    assert promotion.demoted_at is not None
    return base.model_copy(
        update={"updatedAt": max(_aware(base.updatedAt), promotion.demoted_at)}
    )


class SpotStore:
    """In-memory canonical spots plus per-camera observations for multi-camera merge.

    Per spot there is a *base* canonical (merge of observations, or the latest direct
    write) and a *published* canonical (base composed with dwell promotion state).
    Readers see the published spot. Writers hold ``_write_lock`` from computing the new
    state through persisting it, so ``spot_history`` order matches in-memory order;
    ``_lock`` only guards the dicts, so readers never wait on SQLite.
    """

    def __init__(self) -> None:
        self._canonical: dict[str, Spot] = {}
        self._base: dict[str, Spot] = {}
        self._promotions: dict[str, DwellPromotion] = {}
        # Per-spot occupancy-session counter, bumped whenever the base enters
        # ``available``. Never reset, so a checker pass that read the previous
        # session cannot act on the next one.
        self._sessions: dict[str, int] = {}
        self._observations: dict[tuple[str, str], Spot] = {}
        self._merge: MergeConfig = MergeConfig.load(merge_config_path())
        self._lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    def reload_merge_config(self) -> None:
        self._merge = MergeConfig.load(merge_config_path())

    async def bootstrap_from_db(self, spot_rows: list[tuple], obs_rows: list[tuple]) -> None:
        """Rebuild state from SQLite at startup.

        Dwell promotions are in memory only, so a ``spots`` row that is ``soon`` because
        of a dwell promotion is restored as base ``occupied`` (the checker re-promotes it
        if it is still inside the window). A ``soon`` row counts as a dwell promotion when
        it has no camera observations and its open history session saw ``occupied``
        first; a ``soon`` that started the session (a seed) is kept. Status changes made
        here are persisted so ``spot_history`` matches what clients see.
        """
        observed_ids = {r[0] for r in obs_rows}
        restore_ids: set[str] = set()
        for row in spot_rows:
            if row[0] not in observed_ids and row[3] == "soon":
                if "occupied" in await current_session_statuses_db(row[0]):
                    restore_ids.add(row[0])

        async with self._write_lock:
            async with self._lock:
                corrections = self._bootstrap_locked(spot_rows, obs_rows, restore_ids)
            for spot, stored_status in corrections:
                log.info(
                    "Startup: spot %s published as %s (stored %s not kept)",
                    spot.id,
                    spot.status,
                    stored_status,
                )
                await upsert_spot_db(spot)

    def _bootstrap_locked(
        self, spot_rows: list[tuple], obs_rows: list[tuple], restore_ids: set[str]
    ) -> list[tuple[Spot, SpotStatus]]:
        """Rebuild the dicts; return ``(spot, stored_status)`` where the two statuses differ."""
        self._observations.clear()
        for r in obs_rows:
            sid, cam, lat, lng, status, conf, upd = r
            ts = datetime.fromisoformat(upd)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            self._observations[(sid, cam)] = Spot(
                id=sid,
                lat=lat,
                lng=lng,
                status=status,
                confidence=conf,
                updatedAt=ts,
                cameraId=cam,
            )

        self._canonical.clear()
        self._base.clear()
        self._promotions.clear()
        if self._observations:
            spot_ids: set[str] = {s for s, _ in self._observations}
            for sid in spot_ids:
                merged = merge_canonical_for_spot(sid, self._observations, self._merge)
                if merged:
                    self._canonical[sid] = merged
            for row in spot_rows:
                sid = row[0]
                if sid not in self._canonical:
                    self._canonical[sid] = _spot_from_spots_row(row)
        else:
            for row in spot_rows:
                self._canonical[row[0]] = _spot_from_spots_row(row)

        now = datetime.now(timezone.utc)
        for sid in restore_ids:
            spot = self._canonical.get(sid)
            if spot is not None and spot.status == "soon":
                self._canonical[sid] = spot.model_copy(
                    update={"status": "occupied", "updatedAt": max(_aware(spot.updatedAt), now)}
                )
        self._base.update(self._canonical)
        for sid in self._base:
            # Any checker pass still holding pre-bootstrap state becomes a no-op.
            self._sessions[sid] = self._sessions.get(sid, 0) + 1

        stored = {row[0]: row[3] for row in spot_rows}
        return [
            (spot, stored[sid])
            for sid, spot in self._canonical.items()
            if sid in stored and stored[sid] != spot.status
        ]

    async def upsert_canonical(self, spot: Spot, persist: bool = True) -> None:
        """Write canonical spot directly (demo simulator, seeds). Does not update observations.

        Clears any dwell promotion: the written spot is published as-is.
        """
        async with self._write_lock:
            async with self._lock:
                self._set_base_locked(spot.id, spot)
                self._promotions.pop(spot.id, None)
                self._canonical[spot.id] = spot
            if persist:
                await upsert_spot_db(spot)

    async def list_canonical(self) -> list[Spot]:
        async with self._lock:
            return list(self._canonical.values())

    async def list_for_camera(self, camera_id: str) -> list[Spot]:
        async with self._lock:
            return [
                obs.model_copy()
                for (_, cam), obs in self._observations.items()
                if cam == camera_id
            ]

    async def get(self, spot_id: str) -> Spot | None:
        async with self._lock:
            return self._canonical.get(spot_id)

    def _set_base_locked(self, spot_id: str, base: Spot) -> None:
        """Store a new base; entering ``available`` starts a new occupancy session."""
        prev = self._base.get(spot_id)
        if base.status == "available" and (prev is None or prev.status != "available"):
            self._sessions[spot_id] = self._sessions.get(spot_id, 0) + 1
        self._base[spot_id] = base

    def _publish_locked(self, spot_id: str, base: Spot) -> tuple[bool, Spot]:
        """Set base, apply promotion rules, store the published spot. Caller holds ``_lock``."""
        self._set_base_locked(spot_id, base)
        if base.status == "available":
            # Car left: the occupancy session (and its promotion) ends silently.
            self._promotions.pop(spot_id, None)
        published = _compose(base, self._promotions.get(spot_id))
        prev = self._canonical.get(spot_id)
        self._canonical[spot_id] = published
        changed = prev is None or _canonical_fields_differ(prev, published)
        return changed, published

    async def apply_detector_update(self, spot: Spot) -> tuple[bool, Spot]:
        """Apply a detector POST: per-camera observation + merged canonical. Returns (changed, published)."""
        async with self._write_lock:
            if not spot.cameraId:
                async with self._lock:
                    changed, published = self._publish_locked(spot.id, spot)
                if changed:
                    await upsert_spot_db(published)
                return changed, published

            await upsert_observation_db(spot)
            async with self._lock:
                self._observations[(spot.id, spot.cameraId)] = spot
                merged = merge_canonical_for_spot(spot.id, self._observations, self._merge)
                if merged is None:
                    merged = spot
                changed, published = self._publish_locked(spot.id, merged)
            if changed:
                await upsert_spot_db(published)
            return changed, published

    async def dwell_snapshot(self) -> list[DwellCandidate]:
        """Base status, promotion and session counter for every spot, for the dwell checker."""
        async with self._lock:
            return [
                DwellCandidate(
                    sid, base.status, self._promotions.get(sid), self._sessions.get(sid, 0)
                )
                for sid, base in self._base.items()
            ]

    def _session_changed_locked(self, spot_id: str, session: int | None) -> bool:
        return session is not None and self._sessions.get(spot_id, 0) != session

    async def promote_dwell(
        self, spot_id: str, now: datetime, *, session: int | None = None
    ) -> DwellChange:
        """Start a dwell promotion if the spot's base is still ``occupied`` and none exists.

        Re-checks state at apply time, so a car that left while the checker was querying
        dwell stats is not promoted. With *session* (from ``dwell_snapshot``) it is also a
        no-op if a new occupancy session started since, so a car that parked in the
        meantime is not promoted on the previous car's elapsed time.
        """
        async with self._write_lock:
            async with self._lock:
                base = self._base.get(spot_id)
                if (
                    base is None
                    or base.status != "occupied"
                    or spot_id in self._promotions
                    or self._session_changed_locked(spot_id, session)
                ):
                    return DwellChange(False, False, self._canonical.get(spot_id))
                self._promotions[spot_id] = DwellPromotion(promoted_at=_aware(now))
                changed, published = self._publish_locked(spot_id, base)
            if changed:
                await upsert_spot_db(published)
            return DwellChange(True, changed, published)

    async def demote_dwell(
        self, spot_id: str, now: datetime, *, session: int | None = None
    ) -> DwellChange:
        """End an active dwell promotion; the spot is not promoted again this session.

        Publishes the base status: ``occupied``, or detector motion ``soon`` (unchanged).
        With *session*, a no-op if a new occupancy session started since the snapshot.
        """
        async with self._write_lock:
            async with self._lock:
                base = self._base.get(spot_id)
                promotion = self._promotions.get(spot_id)
                if (
                    base is None
                    or promotion is None
                    or not promotion.active
                    or self._session_changed_locked(spot_id, session)
                ):
                    return DwellChange(False, False, self._canonical.get(spot_id))
                self._promotions[spot_id] = DwellPromotion(
                    promoted_at=promotion.promoted_at,
                    demoted_at=_aware(now),
                )
                changed, published = self._publish_locked(spot_id, base)
            if changed:
                await upsert_spot_db(published)
            return DwellChange(True, changed, published)
