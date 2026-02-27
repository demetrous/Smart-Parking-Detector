# Backend

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

On first run it seeds 13 demo spots and starts a built-in simulator that cycles spot states every 2 seconds. Once the detector is wired up, disable the simulator by removing the `asyncio.create_task(simulator_loop())` line in `app/main.py`.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `parking.db` | SQLite database file path |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated allowed origins |

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

## Module layout

```
app/
├── main.py      # App factory, routes, lifespan, simulator loop
├── models.py    # Spot & Event Pydantic models
├── store.py     # SpotStore: in-memory dict + SQLite write-through
├── hub.py       # WebSocket Hub: connect / disconnect / broadcast
└── db.py        # aiosqlite helpers: init_db, upsert_spot_db, load_spots_db
```
