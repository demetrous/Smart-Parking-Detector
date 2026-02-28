# ParkingSpotter — Developer Log & Next Steps

## Status snapshot

| Phase | Status | Summary |
|-------|--------|---------|
| 1 | ✅ Done | Frontend scaffold · FastAPI backend · SQLite · WebSocket |
| 2 | ✅ Done | `draw_slots.py` · `dev.ps1` · smoke test |
| 3 | ✅ Done | Dwell-time "soon" · WS reconnect · offline indicator |
| 4 | ✅ Done | ByteTrack · MotionMonitor · motion-based "soon" |
| 5 | 🔜 Next | Multi-camera + homography |
| 6 | 📋 Planned | Synthetic test stream |
| 7 | 📋 Planned | Docker hardening + GPU + privacy masking |

---

## Phase 1 & 2 — complete

### Project setup
- Renamed from "Smart Parking Detector" → **ParkingSpotter**
- Prior work archived on `v1` branch; `master` is a clean slate

### Backend (`backend/`)
- FastAPI app in focused modules: `models.py`, `store.py`, `hub.py`, `db.py`, `main.py`
- `GET /spots` — returns current spot list (seeded from DB or demo seeds on first run)
- `POST /spots` — detector pushes updates; backend persists + broadcasts
- `WS /ws` — WebSocket hub broadcasts `spot.update` to all connected frontends
- aiosqlite SQLite: `spots` table (current state) + `spot_history` (append-only log)
- Built-in simulator loop (cycles random spots every 2 s) — disabled via `SIMULATOR=false`
- `requirements.txt` uses `>=` lower bounds (fixed Python 3.14 / pydantic-core build issue)

### Frontend (`frontend/`)
- React 19 + TypeScript + Vite 7 + Tailwind CSS v4
- MapLibre GL + MapTiler (`dataviz` / `dataviz-dark` styles for light/dark theme)
- Dark/light theme toggle (persists to `localStorage`, respects `prefers-color-scheme`)
- SVG pin markers (green/yellow/red) with fade animation on occupied → hidden
- Popup: spot ID, status, "Navigate" → Google Maps
- WebSocket client + REST fallback for initial load
- `dev.ps1` — installs packages to `%LOCALAPPDATA%\ParkingSpotter\frontend\node_modules`
  to avoid npm EBADF failures on Google Drive / OneDrive; also copies `@types/react` and
  `@types/react-dom` into the project-local `node_modules\@types` so the IDE finds types
- `vite.launcher.config.ts` — three-layer module resolution bridge (Vite / Rollup / esbuild)
- `.gdriveignore` excludes `node_modules/`, `__pycache__/`, `.pt`, `.db` from sync

### Detector (`detector/`)
- YOLO11 vehicle detection (COCO classes: car 2, truck 7, bus 5, motorcycle 3)
- Per-slot IoU occupancy with polygon config (`slots.json`)
- Debounce state machine — N consecutive frames must agree before publishing
- `draw_slots.py` — interactive OpenCV polygon drawing tool (click, Enter, U/D/S/Q)
- `slots.example.json` — documented template

### Docs & infra
- Root `README.md` with architecture Mermaid diagram, plain-English explanations, quick start, API reference, config tables, roadmap
- `backend/README.md`, `detector/README.md`, `frontend/README.md`
- `docker-compose.yml` skeleton (backend + frontend + optional detector profile)

---

## Phase 3 — complete ✅

### 3a — Detector on real footage (manual / operational)
1. Get a sample parking video (PKLot dataset: https://web.inf.ufpr.br/vri/databases/parking-lot-database/)
2. `cd detector && pip install -r requirements.txt`
3. Draw slot polygons: `python draw_slots.py --source sample.mp4` → saves `slots.json`
4. Run: `python -m detector.main --source sample.mp4 --preview`
5. Set `SIMULATOR=false` in backend env to disable random-cycle loop
6. Verify backend receives `POST /spots` and frontend map updates live

### 3b — Dwell-time "soon" prediction
- `query_dwell_db(spot_id)` in `db.py` — scans `spot_history` for completed occupied→available
  runs, returns `{count, mean, stddev}` in seconds
- `occupied_since_db(spot_id)` — UTC timestamp of most recent occupied transition
- `GET /spots/{id}/dwell` — diagnostic endpoint (also useful for a future "X min remaining" UI)
- `dwell_checker_loop` — background task (active when `SIMULATOR=false`): promotes
  `occupied` → `soon` when `elapsed ≥ SOON_THRESHOLD × mean_dwell`
  (requires ≥ `DWELL_MIN_COUNT` samples to act, preventing false positives on sparse history)
- Env vars: `SIMULATOR` (default `true`), `SOON_THRESHOLD` (default `0.7`),
  `DWELL_MIN_COUNT` (default `3`), `DWELL_CHECK_INTERVAL` (default `15.0` s)

### 3c — WebSocket reconnect & offline indicator
- `connectWs` in `api.ts` → `WsController` interface (`{close()}`); exponential back-off
  1 s → 2 s → 4 s … 30 s; resets on each successful `onopen`
- `onStatus` callback (`"connected" | "disconnected"`) exposed as `connected: boolean`
  on the `SpotsProvider` context
- `Toolbar` in `App.tsx` shows a red **Offline** pill (`SignalSlashIcon`) when disconnected;
  disappears automatically on reconnect

---

## Phase 4 — complete ✅

### ByteTrack motion-based "soon"

**`detector/detector/tracker.py`** (new file)
- `MotionMonitor` class — rolling centroid history (deque) per ByteTrack track ID
- `update(track_id, bbox)` — records centroid this frame
- `is_moving(track_id) → bool` — True if centroid displaced ≥ `threshold` px over the window
- `displacement(track_id) → float` — raw displacement value (useful for debugging threshold)
- `prune(active_ids)` — clears stale track history each frame

**`detector/detector/inference.py`**
- `OccupancyDetector` gains: `enable_tracking`, `motion_window_frames`, `motion_threshold_px`
- `SlotState` gains `_debounced_occupied: bool` — decouples the IoU debounce from the
  published status so "soon" doesn't reset the debounce clock
- `_process_plain()` — original IoU-only path (unchanged; still the default)
- `_process_tracked()` — ByteTrack path:
  1. `model.track(persist=True, tracker="bytetrack.yaml")` replaces `model()`
  2. Builds `track_id → bbox` map for all vehicle detections this frame
  3. Per slot: finds best covering track (highest IoU), updates `MotionMonitor`
  4. Debounce runs on raw IoU signal → drives "available" transitions (stable)
  5. Motion check on top: occupied + moving track → "soon"; stopped → "occupied";
     IoU drops below threshold + debounce confirms → "available"
- `annotate_frame()` — yellow polygon for "soon" slots (was only green/red before)

**`detector/detector/main.py`**
- `--track` flag (default off; fully backward-compatible)
- `--motion-px FLOAT` (default 15.0 px)
- `--motion-frames INT` (default 10 frames)

**Tuning guide**
- Lower `--motion-px` → more sensitive (fires sooner; more false positives from camera vibration)
- Higher `--motion-frames` → more stable (slower to react; good for slow cameras)
- Good starting point: `--motion-px 20 --motion-frames 8` for 15–25 fps cameras

---

## Phase 5 — next 🔜

### Multi-camera support + homography calibration

A single camera only sees part of a large parking lot. Phase 5 adds the ability to run multiple detectors simultaneously, each covering a different zone, all feeding into the same backend.

**Tasks**
- [ ] Each `slots.json` already has a `camera_id` field — backend stores it; slots from different cameras will appear on the same map naturally
- [ ] **Homography calibration tool**: given 4+ known real-world GPS points visible in the camera frame, compute a homography matrix that maps pixel coordinates → GPS coordinates. This means you draw slots in pixel space and the tool auto-computes lat/lng — no manual coordinate lookup.
- [ ] Handle overlapping fields of view: if two cameras see the same slot, define a priority or merge rule so they don't fight over the spot's status
- [ ] Update `draw_slots.py` to optionally accept a homography calibration file and auto-fill lat/lng from clicked pixel coordinates
- [ ] Add `camera_id` filter to `GET /spots?camera=cam_1` so a deployment can scope queries

---

## Phase 6 — planned 📋

### Synthetic test stream (Three.js / CARLA)

The detector is hard to regression-test against a real camera (lighting changes, weather, different vehicles). A synthetic stream gives reproducible, scriptable test scenarios.

**Options**
- **Three.js**: render a top-down 3D parking lot in the browser, export as a video stream via `canvas.captureStream()`. Simple, no GPU needed, good for CI.
- **CARLA**: full autonomous-driving simulator, photorealistic parking scenarios. Overkill for most tests but useful for evaluating model accuracy.

**Tasks**
- [ ] Implement a minimal Three.js parking lot scene with controllable car actors
- [ ] Stream via WebRTC or write frames to a pipe that the detector can consume as `--source`
- [ ] Write a test harness: place car at slot → assert detector emits "occupied" within N frames; move car away → assert "available"

---

## Phase 7 — planned 📋

### Docker Compose hardening · GPU build · Privacy masking

**Tasks**
- [ ] Complete `docker-compose.yml`: health-checks, restart policies, volume mounts for `parking.db` and `slots.json`
- [ ] GPU Dockerfile: `nvidia/cuda` base image, `ultralytics[gpu]` wheels, `--gpus all` flag
- [ ] Privacy masking in `inference.py`: before any frame is stored or displayed, blur faces and licence plates using a lightweight detector (e.g. YOLOv8-face or OpenCV cascade)
- [ ] `.env.example` for Docker deployment (ports, DB path, CORS, etc.)
- [ ] GitHub Actions CI: lint (ruff, eslint), type-check (mypy, tsc), smoke test (start backend + run 10-frame detector on a test clip, assert correct `POST /spots` calls)

---

## Repo state

- **Branch `master`** — active development (Phases 1–4 complete)
- **Branch `v1`** — archived prior work: Leaflet mock + React/Mapbox frontend + original FastAPI monolith
- **GitHub repo** — `github.com/demetrous/Smart-Parking-Detector` (rename to `ParkingSpotter` in Settings when ready)
- **Domain** — `parkingspotter.com` taken; `parkingspotter.io` and `parkingspotter.app` appear available

## Key architectural decisions (for future contributors)

| Decision | Choice | Reason |
|----------|--------|--------|
| Map provider | MapLibre GL + MapTiler | Open-source, free tier (100k loads/month), no Mapbox lock-in |
| Detection model | YOLO11n (Ultralytics) | Latest nano model — fast on CPU, drop-in upgrade path to larger models |
| Occupancy method | Per-slot IoU | More robust than pixel-counting for varied car sizes; simpler than DeepSORT |
| Tracking | ByteTrack (opt-in, `--track`) | Built into Ultralytics — zero extra dependencies for motion "soon" |
| Backend storage | In-memory + SQLite write-through | Zero-ops, survives restarts; history table enables dwell-time prediction |
| Real-time transport | FastAPI WebSocket hub | Single service, no Redis/broker needed at MVP scale |
| "Soon" via history | `spot_history` dwell stats | Needs no camera movement signal; works even with static CCTV footage |
| Frontend state | React Context + WS controller | Simple, no Redux needed at this scale; reconnect logic self-contained in `api.ts` |
