from __future__ import annotations

import asyncio

from .db import upsert_spot_db
from .models import Spot


class SpotStore:
    def __init__(self) -> None:
        self._spots: dict[str, Spot] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, spot: Spot, persist: bool = True) -> None:
        async with self._lock:
            self._spots[spot.id] = spot
        if persist:
            await upsert_spot_db(spot)

    async def list(self) -> list[Spot]:
        async with self._lock:
            return list(self._spots.values())

    async def get(self, spot_id: str) -> Spot | None:
        async with self._lock:
            return self._spots.get(spot_id)
