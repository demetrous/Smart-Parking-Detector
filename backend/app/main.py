from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, load_spots_db
from .hub import Hub
from .models import Event, Spot, SpotStatus
from .store import SpotStore

store = SpotStore()
hub = Hub()


# -----------------------------
# Simulator (stand-in until detector is wired)
# -----------------------------


async def simulator_loop() -> None:
    """Cycle random spot states every 2 s. Replaced by detector in production."""
    order: list[SpotStatus] = ["occupied", "soon", "available"]
    while True:
        await asyncio.sleep(2.0)
        spots = await store.list()
        if not spots:
            continue
        target = random.choice(spots)
        next_status = order[(order.index(target.status) + 1) % len(order)]
        updated = target.model_copy(
            update={
                "status": next_status,
                "updatedAt": datetime.now(timezone.utc),
                "confidence": 0.9,
            }
        )
        await store.upsert(updated)
        await hub.broadcast(
            Event(type="spot.update", payload=updated.model_dump(mode="json"))
        )


# -----------------------------
# Lifespan
# -----------------------------

_DEMO_SEEDS: list[Spot] = [
    Spot(id="A1", lat=47.62319, lng=-122.3546, status="available"),
    Spot(id="A2", lat=47.62270, lng=-122.3539, status="soon"),
    Spot(id="B1", lat=47.62190, lng=-122.3527, status="occupied"),
    Spot(id="B2", lat=47.62230, lng=-122.3506, status="available"),
    Spot(id="C1", lat=47.62160, lng=-122.3515, status="occupied"),
    Spot(id="C2", lat=47.622969, lng=-122.355528, status="available"),
    Spot(id="C3", lat=47.622719, lng=-122.355542, status="available"),
    Spot(id="C4", lat=47.622662, lng=-122.355544, status="occupied"),
    Spot(id="C5", lat=47.623118, lng=-122.356099, status="available"),
    Spot(id="C6", lat=47.623323, lng=-122.355667, status="available"),
    Spot(id="C7", lat=47.621223, lng=-122.355483, status="occupied"),
    Spot(id="C8", lat=47.620595, lng=-122.355494, status="soon"),
    Spot(id="C9", lat=47.620908, lng=-122.356372, status="available"),
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()

    # Restore persisted state from SQLite; fall back to demo seeds on first run
    rows = await load_spots_db()
    if rows:
        for row in rows:
            spot = Spot(
                id=row[0],
                lat=row[1],
                lng=row[2],
                status=row[3],
                confidence=row[4],
                cameraId=row[5],
                updatedAt=datetime.fromisoformat(row[6]),
            )
            await store.upsert(spot, persist=False)
    else:
        for s in _DEMO_SEEDS:
            await store.upsert(s)

    asyncio.create_task(simulator_loop())
    yield


# -----------------------------
# App factory
# -----------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="ParkingSpotter Backend", version="0.2.0", lifespan=lifespan)

    default_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
    cors_origins = os.getenv("CORS_ORIGINS", ",".join(default_origins)).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}

    @app.get("/spots", response_model=list[Spot])
    async def list_spots() -> list[Spot]:
        return await store.list()

    @app.post("/spots")
    async def upsert_spot(spot: Spot) -> dict:
        """Detector pushes updates here; backend persists and broadcasts."""
        await store.upsert(spot)
        await hub.broadcast(
            Event(type="spot.update", payload=spot.model_dump(mode="json"))
        )
        return {"ok": True}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(ws)

    return app


app = create_app()
