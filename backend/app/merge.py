from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .models import Spot


@dataclass
class MergeConfig:
    """Deterministic camera priority for merging per-camera observations into one canonical spot."""

    default_priority: list[str] = field(default_factory=list)
    per_spot: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | None) -> "MergeConfig":
        if path is None or not path.is_file():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            default_priority=list(data.get("default_priority", [])),
            per_spot={k: list(v) for k, v in data.get("per_spot", {}).items()},
        )


def merge_canonical_for_spot(
    spot_id: str,
    observations: dict[tuple[str, str], Spot],
    config: MergeConfig,
) -> Spot | None:
    """Pick one observation as canonical using configured camera order, then remaining cameras alphabetically."""
    by_cam: dict[str, Spot] = {}
    for (sid, cam_id), obs in observations.items():
        if sid != spot_id or not cam_id:
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
