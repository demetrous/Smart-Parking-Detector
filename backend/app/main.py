from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# -----------------------------
# Models
# -----------------------------

SpotStatus = Literal["available", "soon", "occupied"]


class Spot(BaseModel):
    id: str
    lat: float
    lng: float
    status: SpotStatus = Field(default="occupied")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    updatedAt: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    cameraId: str | None = None


class Event(BaseModel):
    type: str
    payload: dict


# -----------------------------
# Store
# -----------------------------


class SpotStore:
    def __init__(self) -> None:
        self._spots: dict[str, Spot] = {}
        self._lock = asyncio.Lock()

    async def upsert(self, spot: Spot) -> None:
        async with self._lock:
            self._spots[spot.id] = spot

    async def list(self) -> list[Spot]:
        async with self._lock:
            return list(self._spots.values())

    async def get(self, spot_id: str) -> Spot | None:
        async with self._lock:
            return self._spots.get(spot_id)


store = SpotStore()


# -----------------------------
# WebSocket Hub
# -----------------------------


class Hub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)

    async def broadcast(self, event: Event) -> None:
        message = event.model_dump_json()
        async with self._lock:
            targets = list(self._connections)
        for ws in targets:
            try:
                await ws.send_text(message)
            except Exception:
                # best-effort; drop failed connection
                await self.disconnect(ws)


hub = Hub()


# -----------------------------
# FastAPI app
# -----------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="Smart Parking Backend", version="0.1.0")

    # CORS
    default_origins = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    cors_origins = os.getenv("CORS_ORIGINS", ",".join(default_origins)).split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cors_origins if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health():  # pragma: no cover - trivial
        return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}

    @app.get("/spots", response_model=list[Spot])
    async def list_spots():
        return await store.list()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await hub.connect(ws)
        try:
            while True:
                # Keep the connection alive; ignore incoming messages for now
                await ws.receive_text()
        except WebSocketDisconnect:
            await hub.disconnect(ws)

    @app.on_event("startup")
    async def on_startup():
        # Seed some demo spots
        seeds = [
            Spot(id="A1", lat=47.62319, lng=-122.3546, status="available"),
            Spot(id="A2", lat=47.62270, lng=-122.3539, status="soon"),
            Spot(id="B1", lat=47.62190, lng=-122.3527, status="occupied"),
            Spot(id="B2", lat=47.62230, lng=-122.3506, status="available"),
            Spot(id="C1", lat=47.62160, lng=-122.3515, status="occupied"),
        ]
        for s in seeds:
            await store.upsert(s)

        # Start simulator
        app.add_event_handler("startup", lambda: None)  # quiet lint
        asyncio.create_task(simulator_loop())

    return app


app = create_app()


# -----------------------------
# Simulator
# -----------------------------


async def simulator_loop() -> None:
    """Flip random spot states periodically and broadcast updates.

    This is a lightweight stand-in until the detector publishes real updates.
    """
    import random

    order: list[SpotStatus] = ["occupied", "soon", "available"]
    while True:
        await asyncio.sleep(2.0)
        spots = await store.list()
        if not spots:
            continue
        target = random.choice(spots)
        next_status = order[(order.index(target.status) + 1) % len(order)]
        updated = target.model_copy(update={
            "status": next_status,
            "updatedAt": datetime.now(timezone.utc),
            "confidence": 0.9,
        })
        await store.upsert(updated)
        await hub.broadcast(Event(type="spot.update", payload=updated.model_dump()))


