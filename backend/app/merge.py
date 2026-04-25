from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .models import Spot


@dataclass
class MergeConfig:
    """Deterministic camera priority for merging per-camera observations into one canonical spot."""

    default_priority: list[str] = field(default_factory=list)
    per_spot: dict[str, list[str]] = field(default_factory=dict)
    #: If set, observations older than this many seconds are ignored for merge (stale camera).
    max_observation_age_seconds: float | None = None

    @classmethod
    def load(cls, path: Path | None) -> "MergeConfig":
        if path is None or not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        max_age: float | None
        raw_json = data.get("max_observation_age_seconds")
        env_raw = os.getenv("MERGE_MAX_OBSERVATION_AGE_SECONDS", "").strip()
        if env_raw:
            max_age = float(env_raw)
        elif raw_json is not None:
            max_age = float(raw_json)
        else:
            max_age = None
        return cls(
            default_priority=list(data.get("default_priority", [])),
            per_spot={k: list(v) for k, v in data.get("per_spot", {}).items()},
            max_observation_age_seconds=max_age,
        )


def merge_canonical_for_spot(
    spot_id: str,
    observations: dict[tuple[str, str], Spot],
    config: MergeConfig,
    *,
    now: datetime | None = None,
) -> Spot | None:
    """Pick one observation as canonical using configured camera order, then remaining cameras alphabetically."""
    now = now or datetime.now(timezone.utc)
    by_cam: dict[str, Spot] = {}
    max_age = config.max_observation_age_seconds
    for (sid, cam_id), obs in observations.items():
        if sid != spot_id or not cam_id:
            continue
        if max_age is not None:
            ts = obs.updatedAt
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_s = (now - ts).total_seconds()
            if age_s > max_age:
                continue
        by_cam[cam_id] = obs

    if not by_cam:
        return None

    explicit = list(config.per_spot.get(spot_id, config.default_priority))
    seen: set[str] = set()
    order: list[str] = []
    for c in explicit:
        if c and c not in seen:
            seen.add(c)
            order.append(c)
    for c in sorted(by_cam):
        if c not in seen:
            seen.add(c)
            order.append(c)

    for cam_id in order:
        if cam_id in by_cam:
            obs = by_cam[cam_id]
            return Spot(
                id=spot_id,
                lat=obs.lat,
                lng=obs.lng,
                status=obs.status,
                confidence=obs.confidence,
                updatedAt=obs.updatedAt,
                cameraId=cam_id,
            )
    return None


def merge_config_path() -> Path | None:
    raw = os.getenv("MERGE_CONFIG_PATH", "").strip()
    if not raw:
        return None
    return Path(raw)
