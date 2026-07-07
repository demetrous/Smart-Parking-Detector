from __future__ import annotations

import asyncio
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from collections.abc import Coroutine
from typing import Any, AsyncGenerator

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from .auth import HEADER_SIGNATURE, HEADER_TIMESTAMP, verify_signed_detector_request
from .db import (
    init_db,
    load_observations_db,
    load_spots_db,
    occupied_since_db,
    query_dwell_db,
    seed_dwell_demo_sparse,
)
from .hub import Hub
from .models import Event, Spot, SpotStatus
from .project_models import ProjectCreate, ProjectListResponse, ProjectManifest, ProjectPatch
from .project_store import (
    asset_path,
    create_project,
    export_project_zip,
    import_project_zip,
    list_projects,
    patch_project,
    read_manifest,
    save_project_asset,
)
from .store import SpotStore

store = SpotStore()
hub = Hub()

_background_tasks: set[asyncio.Task[None]] = set()


def _spawn_background(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _env_truthy(key: str) -> bool:
    return os.getenv(key, "").strip().lower() in ("1", "true", "yes", "on")


def _simulator_enabled() -> bool:
    return os.getenv("SIMULATOR", "true").lower() not in ("0", "false", "no")


def _dwell_checker_enabled() -> bool:
    """Run dwell-time 'soon' promotion. On by default when the random simulator is off."""
    if not _simulator_enabled():
        return True
    return _env_truthy("PARKINGSPOTTER_DWELL_CHECK_WITH_SIMULATOR")


# -----------------------------
# Simulator (stand-in until detector is wired)
# -----------------------------


async def simulator_loop() -> None:
    """Cycle random spot states every 2 s. Replaced by detector in production."""
    order: list[SpotStatus] = ["occupied", "soon", "available"]
    while True:
        await asyncio.sleep(2.0)
        spots = await store.list_canonical()
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
        await store.upsert_canonical(updated)
        await hub.broadcast(
            Event(type="spot.update", payload=updated.model_dump(mode="json"))
        )


# SOON_THRESHOLD  – fraction of mean dwell after which an occupied spot is
#                   promoted to "soon".  Default 0.7 (70 %).
# DWELL_MIN_COUNT – minimum completed dwell samples required before the
#                   checker acts (avoids acting on too little history).
_SOON_THRESHOLD = float(os.getenv("SOON_THRESHOLD", "0.7"))
_DWELL_MIN_COUNT = int(os.getenv("DWELL_MIN_COUNT", "3"))
_DWELL_CHECK_INTERVAL = float(os.getenv("DWELL_CHECK_INTERVAL", "15.0"))
_CAMERA_OFFLINE_AFTER_SECONDS = float(os.getenv("CAMERA_OFFLINE_AFTER_SECONDS", "120"))


async def dwell_checker_loop() -> None:
    """Promote occupied spots to 'soon' when dwell-time threshold is crossed.

    Requires at least DWELL_MIN_COUNT completed dwell samples in spot_history
    so the checker only acts once there is meaningful historical data.
    Designed to run alongside the real detector (simulator disabled).
    """
    while True:
        await asyncio.sleep(_DWELL_CHECK_INTERVAL)
        spots = await store.list_canonical()
        for spot in spots:
            if spot.status != "occupied":
                continue
            dwell = await query_dwell_db(spot.id)
            if dwell["mean"] is None or dwell["count"] < _DWELL_MIN_COUNT:
                continue
            since = await occupied_since_db(spot.id)
            if since is None:
                continue
            elapsed = max(
                0.0,
                (datetime.now(timezone.utc) - since).total_seconds(),
            )
            if elapsed >= _SOON_THRESHOLD * dwell["mean"]:
                updated = spot.model_copy(
                    update={
                        "status": "soon",
                        "updatedAt": datetime.now(timezone.utc),
                    }
                )
                await store.upsert_canonical(updated)
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

    rows = await load_spots_db()
    obs_rows = await load_observations_db()
    if rows or obs_rows:
        await store.bootstrap_from_db(rows, obs_rows)
    else:
        for s in _DEMO_SEEDS:
            await store.upsert_canonical(s)

    if _env_truthy("PARKINGSPOTTER_SEED_DWELL_DEMO"):
        target = max(_DWELL_MIN_COUNT, 3)
        await seed_dwell_demo_sparse(["A1", "B2", "C1"], target)

    if _simulator_enabled():
        _spawn_background(simulator_loop())
    if _dwell_checker_enabled():
        _spawn_background(dwell_checker_loop())
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
    async def list_spots(camera: str | None = Query(None, description="Filter to spots last reported by this camera")) -> list[Spot]:
        if camera:
            return await store.list_for_camera(camera)
        return await store.list_canonical()

    @app.get("/spots/{spot_id}/dwell")
    async def get_dwell(spot_id: str) -> dict:
        """Return historical dwell-time statistics for a spot.

        Response: {"count": int, "mean": float | null, "stddev": float | null}
        where mean/stddev are in seconds.  count < DWELL_MIN_COUNT means not
        enough data yet for reliable "soon" predictions.
        """
        return await query_dwell_db(spot_id)

    @app.get("/analytics/summary")
    async def analytics_summary() -> dict:
        """Pilot-facing current utilization and dwell-readiness summary."""
        spots = await store.list_canonical()
        status_counts: dict[str, int] = {"available": 0, "soon": 0, "occupied": 0}
        dwell_ready = 0
        dwell_by_spot: dict[str, dict] = {}
        for spot in spots:
            status_counts[spot.status] = status_counts.get(spot.status, 0) + 1
            dwell = await query_dwell_db(spot.id)
            dwell_by_spot[spot.id] = dwell
            if dwell["count"] >= _DWELL_MIN_COUNT:
                dwell_ready += 1

        total = len(spots)
        available_now = status_counts.get("available", 0)
        return {
            "totalSpots": total,
            "statusCounts": status_counts,
            "availableRatio": round(available_now / total, 4) if total else None,
            "dwellReadySpots": dwell_ready,
            "dwellMinCount": _DWELL_MIN_COUNT,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "dwellBySpot": dwell_by_spot,
        }

    @app.get("/cameras")
    async def camera_health(
        offline_after_seconds: float = Query(
            _CAMERA_OFFLINE_AFTER_SECONDS,
            gt=0,
            description="Seconds without an observation before a camera is marked offline",
        )
    ) -> list[dict]:
        """Return last-observation health for each reporting camera."""
        now = datetime.now(timezone.utc)
        cameras: dict[str, dict] = {}
        for spot_id, camera_id, _lat, _lng, status, _conf, raw_updated_at in await load_observations_db():
            updated_at = datetime.fromisoformat(raw_updated_at)
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (now - updated_at.astimezone(timezone.utc)).total_seconds())
            current = cameras.get(camera_id)
            if current is None or updated_at > current["_updatedAt"]:
                observed_spots = {spot_id}
                if current is not None:
                    observed_spots.update(current["observedSpots"])
                cameras[camera_id] = {
                    "cameraId": camera_id,
                    "lastObservedAt": updated_at.isoformat(),
                    "ageSeconds": round(age_seconds, 2),
                    "online": age_seconds <= offline_after_seconds,
                    "observedSpots": observed_spots,
                    "lastStatus": status,
                    "_updatedAt": updated_at,
                }
            else:
                current["observedSpots"].add(spot_id)

        result: list[dict] = []
        for camera in cameras.values():
            observed = sorted(camera.pop("observedSpots"))
            camera.pop("_updatedAt", None)
            camera["observedSpotCount"] = len(observed)
            camera["observedSpots"] = observed
            result.append(camera)
        return sorted(result, key=lambda c: c["cameraId"])

    @app.get("/spots.csv")
    async def export_spots_csv() -> Response:
        """CSV export for pilot dashboards and spreadsheet workflows."""
        rows = ["id,status,lat,lng,confidence,camera_id,updated_at"]
        for spot in await store.list_canonical():
            rows.append(
                ",".join(
                    [
                        spot.id,
                        spot.status,
                        str(spot.lat),
                        str(spot.lng),
                        str(spot.confidence),
                        spot.cameraId or "",
                        spot.updatedAt.isoformat(),
                    ]
                )
            )
        return Response("\n".join(rows) + "\n", media_type="text/csv")

    @app.get("/projects", response_model=ProjectListResponse)
    async def get_projects() -> ProjectListResponse:
        """List portable street/map projects saved on this backend."""
        return ProjectListResponse(projects=list_projects())

    @app.post("/projects", response_model=ProjectManifest)
    async def create_portable_project(payload: ProjectCreate) -> ProjectManifest:
        return create_project(payload)

    @app.get("/projects/{project_id}", response_model=ProjectManifest)
    async def get_portable_project(project_id: str) -> ProjectManifest:
        return read_manifest(project_id)

    @app.patch("/projects/{project_id}", response_model=ProjectManifest)
    async def update_portable_project(project_id: str, payload: ProjectPatch) -> ProjectManifest:
        return patch_project(project_id, payload)

    @app.post("/projects/{project_id}/assets")
    async def upload_project_asset(
        project_id: str,
        file: UploadFile = File(...),
        kind: str = Query("asset", pattern="^(media|calibration|detections|geometry|asset)$"),
    ) -> dict:
        return (await save_project_asset(project_id, file, kind)).model_dump(mode="json")

    @app.get("/projects/{project_id}/assets/{asset_relative_path:path}")
    async def get_project_asset(project_id: str, asset_relative_path: str) -> FileResponse:
        return FileResponse(asset_path(project_id, asset_relative_path))

    @app.get("/projects/{project_id}/export")
    async def export_portable_project(project_id: str) -> Response:
        manifest = read_manifest(project_id)
        payload = export_project_zip(project_id)
        safe_name = manifest.id.replace("/", "-")
        return Response(
            payload,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.zip"'},
        )

    @app.post("/projects/import")
    async def import_portable_project(file: UploadFile = File(...)) -> dict:
        try:
            result = await import_project_zip(file)
        except HTTPException:
            raise
        return result.model_dump(mode="json")

    @app.post("/spots")
    async def upsert_spot(request: Request) -> dict:
        """Detector pushes updates here; backend persists and broadcasts."""
        raw_body = await request.body()
        verify_signed_detector_request(
            raw_body=raw_body,
            timestamp=request.headers.get(HEADER_TIMESTAMP),
            signature=request.headers.get(HEADER_SIGNATURE),
        )
        spot = Spot.model_validate_json(raw_body)
        changed, canonical = await store.apply_detector_update(spot)
        if changed:
            await hub.broadcast(
                Event(type="spot.update", payload=canonical.model_dump(mode="json"))
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
