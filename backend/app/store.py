from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from .db import upsert_observation_db, upsert_spot_db
from .merge import MergeConfig, merge_canonical_for_spot, merge_config_path
from .models import Spot


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


class SpotStore:
    """In-memory canonical spots plus per-camera observations for multi-camera merge."""

    def __init__(self) -> None:
        self._canonical: dict[str, Spot] = {}
        self._observations: dict[tuple[str, str], Spot] = {}
        self._merge: MergeConfig = MergeConfig.load(merge_config_path())
        self._lock = asyncio.Lock()

    def reload_merge_config(self) -> None:
        self._merge = MergeConfig.load(merge_config_path())

    async def bootstrap_from_db(self, spot_rows: list[tuple], obs_rows: list[tuple]) -> None:
        async with self._lock:
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

    async def upsert_canonical(self, spot: Spot, persist: bool = True) -> None:
        """Write canonical spot directly (demo simulator, seeds). Does not update observations."""
        async with self._lock:
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

    async def apply_detector_update(self, spot: Spot) -> tuple[bool, Spot]:
        """Apply a detector POST: per-camera observation + merged canonical. Returns (changed, canonical)."""
        if not spot.cameraId:
            async with self._lock:
                prev = self._canonical.get(spot.id)
                self._canonical[spot.id] = spot
                changed = prev is None or _canonical_fields_differ(prev, spot)
            if changed:
                await upsert_spot_db(spot)
            return changed, spot

        await upsert_observation_db(spot)
        async with self._lock:
            self._observations[(spot.id, spot.cameraId)] = spot
            merged = merge_canonical_for_spot(spot.id, self._observations, self._merge)
            if merged is None:
                merged = spot
            prev = self._canonical.get(spot.id)
            self._canonical[spot.id] = merged
            changed = prev is None or _canonical_fields_differ(prev, merged)
        if changed:
            await upsert_spot_db(merged)
        return changed, merged
