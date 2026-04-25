# ParkingSpotter — Backend

FastAPI service that stores parking spot state, broadcasts real-time updates to the frontend over WebSocket, and persists a history log to SQLite.

## Stack

- **FastAPI** + **Uvicorn** — async HTTP + WebSocket server
- **Pydantic v2** — request/response validation
- **aiosqlite** — async SQLite for state persistence and history

## Setup

```bash
cd backend
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The server starts at `http://127.0.0.1:8000`.

On first run it seeds 13 demo spots and starts a built-in simulator that cycles spot states every 2 seconds. Once the detector is wired up, set `SIMULATOR=false` in the environment so the random simulator does not interfere.

## Docker

```bash
docker compose up backend
```

The backend container:

- listens on port `8000`
- persists SQLite data in the Compose-managed `backend_data` volume
- exposes `/health` for healthchecks
- expects `PARKINGSPOTTER_SHARED_SECRET` to match the detector when real ingest is enabled

**Production / pilot notes:** back up the SQLite file backing `DB_PATH` regularly; set `CORS_ORIGINS` to your real frontend origin; use `MERGE_CONFIG_PATH` when multiple cameras can see the same spot IDs. Keep the shared detector secret out of version control.

## Tests

```bash
python -m pytest
```

Current backend coverage includes:

- signed vs unsigned detector ingest
- dwell-session parsing
- SQLite spot upsert behavior

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `parking.db` | SQLite database file path |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins |
| `PARKINGSPOTTER_SHARED_SECRET` | — | Required in production for signed `POST /spots` (must match detector) |
| `MERGE_CONFIG_PATH` | — | Optional JSON merge rules for multi-camera (`backend/merge.example.json`) |
| `CAMERA_OFFLINE_AFTER_SECONDS` | `120` | Default stale-camera threshold used by `GET /cameras` |
| `PARKINGSPOTTER_SEED_DWELL_DEMO` | — | If `true`/`1`/`on`, inserts **past** synthetic `spot_history` for demo spots so dwell stats populate quickly (**dev/demo only**). |
| `PARKINGSPOTTER_DWELL_CHECK_WITH_SIMULATOR` | — | If `true`, runs the dwell “soon” checker even when `SIMULATOR=true` (default is simulator **or** checker, not both). |

## API Reference

### `GET /health`
Returns `{"ok": true, "time": "<ISO timestamp>"}`.

### `GET /spots`
Returns the current list of all parking spots.

```json
[
  {
    "id": "A1",
    "lat": 47.62319,
    "lng": -122.3546,
    "status": "available",
    "confidence": 1.0,
    "updatedAt": "2026-02-27T12:00:00Z",
    "cameraId": null
  }
]
```

### `GET /analytics/summary`
Returns pilot-facing utilization: current status counts, available ratio, dwell readiness, and dwell stats per spot.

### `GET /cameras`
Returns one row per reporting camera with `lastObservedAt`, `ageSeconds`, `online`, `observedSpotCount`, and `observedSpots`. Use `?offline_after_seconds=...` to tune the stale-camera threshold per deployment.

### `GET /spots.csv`
Exports the current canonical spot state as CSV for spreadsheet workflows, dashboard imports, and quick pilot integrations.

### `POST /spots`
Upsert a spot. Used by the detector to push state changes. The backend persists the update to SQLite and broadcasts a `spot.update` event to all WebSocket clients.

Request body: same shape as a spot object above.

### `WS /ws`
WebSocket endpoint. Clients connect here to receive real-time `spot.update` events:

```json
{
  "type": "spot.update",
  "payload": { ...spot }
}
```

## Database

Two SQLite tables:

- **`spots`** — current state mirror, one row per spot. Restored on restart so the map is never empty.
- **`spot_history`** — append-only log of every status change. Foundation for dwell-time "soon" predictions in Phase 3.

## Privacy posture for pilots

The backend stores spot IDs, coordinates, statuses, confidence, camera IDs, and timestamps. It does **not** store raw video frames or license plate data. Keep raw camera streams inside the detector environment unless a deployment has an explicit retention and privacy policy.

## Module layout

```
app/
├── main.py      # App factory, routes, lifespan, simulator loop
├── models.py    # Spot & Event Pydantic models
├── store.py     # SpotStore: in-memory dict + SQLite write-through
├── hub.py       # WebSocket Hub: connect / disconnect / broadcast
└── db.py        # aiosqlite helpers: init_db, upsert_spot_db, load_spots_db
```
