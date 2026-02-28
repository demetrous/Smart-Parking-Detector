# ParkingSpotter — Progress & Next Steps

## What's done (Phase 1 complete)

### Project setup
- Renamed from "Smart Parking Detector" to **ParkingSpotter**
- Prior work (Leaflet mock + first React/Mapbox frontend) archived on `v1` branch
- `master` is a clean slate with only `Description/` reference assets + new scaffold

### Backend (`backend/`)
- **FastAPI** app split into focused modules: `models.py`, `store.py`, `hub.py`, `db.py`, `main.py`
- **`GET /spots`** — returns current spot list (seeded from DB or demo data on first run)
- **`POST /spots`** — detector pushes updates here; backend persists + broadcasts
- **`WS /ws`** — WebSocket hub broadcasts `spot.update` events to all connected frontends
- **aiosqlite** SQLite persistence: `spots` table (current state, survives restarts) + `spot_history` table (append-only log of every status change — foundation for Phase 3 "soon" prediction)
- Built-in **simulator loop** (cycles random spots every 2 s) — stand-in until detector is wired
- Modern `lifespan` context manager (no deprecated `on_event`)

### Frontend (`frontend/`)
- **React 19 + TypeScript + Vite 7 + Tailwind CSS v4**
- **Mapbox → MapLibre GL** swap: `maplibre-gl` + `react-map-gl/maplibre`
- **MapTiler** tile provider (free tier, no credit card): `dataviz` (light) + `dataviz-dark` styles toggled by theme
- All CSS class prefixes updated: `mapboxgl-` → `maplibregl-`
- Dark/light theme toggle (persists to `localStorage`, respects `prefers-color-scheme`)
- SVG pin markers (green/yellow/red) with fade animation for occupied→hidden transition
- Popup: spot ID, status with color, "Navigate" link → Google Maps
- WebSocket client auto-connects; REST fallback for initial load
- `VITE_MAPTILER_KEY` + `VITE_API_URL` env vars (see `ENV_EXAMPLE.txt`)

### Detector (`detector/`)
- **YOLO11** (Ultralytics) vehicle detection — COCO classes: car (2), truck (7), bus (5), motorcycle (3)
- **Per-slot IoU occupancy**: define parking slot polygons in `slots.json`; any detected vehicle bbox with IoU ≥ threshold → occupied
- **Debounce state machine**: requires N consecutive frames to agree before publishing a change (avoids flicker)
- **`POST /spots`** push to backend on confirmed status change
- CLI: `python -m detector.main --source 0|video.mp4|rtsp://...` with `--preview` flag for annotated window
- `slots.example.json` template with polygon format documented

### Docs & infra
- Root `README.md` with architecture Mermaid diagram, quick start, folder layout, config tables, roadmap
- `backend/README.md`, `detector/README.md`, `frontend/README.md`
- `docker-compose.yml` skeleton (backend + frontend + optional detector profile)
- `.gitignore` covers Python, Node, `.env`, `.pt` weights, SQLite files

---

## Key architectural decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Map provider | MapLibre GL + MapTiler | Free, open-source, no Mapbox lock-in; free 100k loads/month |
| Detection model | YOLO11n (Ultralytics) | Latest nano model, drop-in from YOLOv8, good CPU speed |
| Occupancy method | Per-slot IoU (no tracking) | Simpler and more reliable than DeepSORT for fixed cameras |
| Tracking | Deferred to Phase 4 | ByteTrack only needed for "pulling in/out" motion detection |
| Backend storage | In-memory dict + SQLite write-through | Zero-ops, survives restarts, history enables Phase 3 |
| Real-time | FastAPI WebSocket hub | Single service, no Redis/broker needed for MVP |
| "Soon" state | Placeholder (simulator only) | Will use `spot_history` dwell-time in Phase 3 |

---

## Immediate next steps (Phase 2)

### 2a — Run the detector on real footage
1. Download a sample parking video (or use PKLot dataset: https://web.inf.ufpr.br/vri/databases/parking-lot-database/)
2. `cd detector && pip install -r requirements.txt`
3. Copy `slots.example.json` → `slots.json`, draw polygons on a sample frame
4. Run: `python -m detector.main --source sample.mp4 --preview`
5. Verify that backend receives `POST /spots` and frontend map updates live

### 2b — Frontend install & smoke test
1. `cd frontend && npm install`
2. Get a free MapTiler key at maptiler.com
3. `cp ENV_EXAMPLE.txt .env` and fill in `VITE_MAPTILER_KEY`
4. `npm run dev` → verify map loads, spots appear, theme toggle works
5. Run backend simultaneously: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload`

### 2c — Slot polygon tool (nice-to-have for Phase 2)
- Simple OpenCV script: open a frame, click to define polygon vertices, save to `slots.json`
- Eliminates manual pixel coordinate lookup

---

## Phase 3+ backlog

| Phase | Deliverable |
|-------|-------------|
| 3 | "Soon" (yellow) via dwell-time: query `spot_history`, if car has been stationary for X% of typical dwell → yellow |
| 4 | ByteTrack integration for motion-based "soon" (car pulling in/out of slot) |
| 5 | Multi-camera: homography calibration, merge overlapping slot views |
| 6 | Three.js or CARLA synthetic stream for regression testing edge cases |
| 7 | Docker Compose hardening, GPU Dockerfile, privacy masking (blur faces/plates) |

---

## Repo state

- **Branch `master`** — current clean scaffold (this document)
- **Branch `v1`** — archived prior work: Leaflet mock + React/Mapbox frontend + original FastAPI monolith
- **GitHub repo** — `github.com/demetrous/Smart-Parking-Detector` (rename to `ParkingSpotter` in repo Settings when ready)
- **Domain** — `parkingspotter.com` taken; `parkingspotter.io` and `parkingspotter.app` appear available
