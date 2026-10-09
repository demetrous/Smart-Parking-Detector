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

**Production / pilot notes:** back up the SQLite database backing `DB_PATH` regularly with `sqlite3 parking.db ".backup parking-backup.db"` (WAL mode keeps recent writes in `parking.db-wal`, so copying only the `.db` file can miss them); set `CORS_ORIGINS` to your real frontend origin; use `MERGE_CONFIG_PATH` when multiple cameras can see the same spot IDs. Keep the shared detector secret out of version control.

## Tests

```bash
python -m pytest
```

Current backend coverage includes:

- signed vs unsigned detector ingest
- dwell-session parsing
- SQLite spot upsert behavior
- SQLite WAL + busy_timeout and `spot_history` retention

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `parking.db` | SQLite database file path (WAL mode; needs a local filesystem) |
| `PARKINGSPOTTER_HISTORY_RETENTION_DAYS` | `90` | Delete `spot_history` sessions that ended more than this many days ago, once at startup and then daily. A spot's open session and any session that crosses the cutoff are kept whole. `0` keeps history forever; invalid values log a warning and use `90`, values above `36500` (100 years) are capped at `36500` |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins |
| `PARKINGSPOTTER_SHARED_SECRET` | — | Required in production for signed `POST /spots` (must match detector) |
| `MERGE_CONFIG_PATH` | — | Optional JSON merge rules for multi-camera (`backend/merge.example.json`) |
| `PARKINGSPOTTER_PROJECTS_TOKEN` | — | Bearer token required on project writes (`POST /projects`, `PATCH /projects/{id}`, `POST /projects/{id}/assets`, `POST /projects/import`). Unset = open writes plus a startup warning (local dev only) |
| `PARKINGSPOTTER_MAX_UPLOAD_MB` | `512` | Max project asset upload and import ZIP size (`413` above it) |
| `PARKINGSPOTTER_MAX_ZIP_ENTRIES` | `2000` | Max entries in an imported project ZIP |
| `PARKINGSPOTTER_MAX_ZIP_UNCOMPRESSED_MB` | `1024` | Max total uncompressed size of an imported project ZIP |
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

SQLite tables:

- **`spots`** — current state mirror, one row per spot. Restored on restart so the map is never empty.
- **`spot_observations`** — latest view of each spot per camera, for multi-camera merge.
- **`spot_history`** — log of every status change. Foundation for dwell-time "soon" predictions. Kept for `PARKINGSPOTTER_HISTORY_RETENTION_DAYS` (default 90): whole dwell sessions that ended before the cutoff are deleted, a session crossing the cutoff and a spot's current open session are kept, so dwell stats inside the window never change.

Every query opens its connection through `db.connect()`, which sets `busy_timeout=5000` and puts the database in WAL mode, so map reads never wait on detector writes and short write overlaps wait instead of failing with `database is locked`. WAL adds `parking.db-wal` and `parking.db-shm` next to the database; they are part of it.

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
