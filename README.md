# ParkingSpotter

> A real-time parking availability system: point a camera at a parking lot, and anyone with a browser sees a live map of which spots are free, taken, or about to open up.

---

## What does it do?

Imagine a parking lot with a camera mounted overhead. ParkingSpotter watches that camera, uses AI to recognise cars, and puts coloured pins on an interactive map — one pin per parking spot.

| Pin colour | What it means | How it's decided |
|------------|---------------|------------------|
| 🟢 **Green** | Empty — park here now | No vehicle detected in this spot |
| 🟡 **Yellow** | Probably freeing up soon | Car has been there a long time *and* is likely leaving, or it's visibly moving/pulling out |
| 🔴 **Red** | Taken | A vehicle is covering this spot |

The map updates **instantly** as things change — no page refresh needed.

---

## Why two ways to show "soon"?

"Soon" is the most useful signal for a driver circling the block. ParkingSpotter produces it two ways:

1. **Dwell-time prediction** — the backend keeps a history of how long cars typically park in each spot. When a car has been there for, say, 70 % of the average parking duration, the spot turns yellow. Like knowing a parking meter is about to expire.

2. **Motion detection** — the detector (camera AI) uses vehicle tracking (ByteTrack) to watch whether a car inside a slot has started moving. The moment it detects the car pulling out, the spot turns yellow immediately — no waiting for a timer.

Both signals feed into the same yellow pin on the map.

---

## How the system is built — plain English

ParkingSpotter has three separate pieces that talk to each other:

```
Camera feed  →  Detector (AI)  →  Backend (server)  →  Frontend (map in browser)
```

### 1 — The Detector (the eyes)

A Python program watches a video stream (a webcam, a video file, or a network camera). Each frame is analysed by a pre-trained AI model called **YOLO11** that can recognise cars, trucks, buses, and motorcycles in real time.

For every parking slot you defined (you draw them once as polygons on the video), the detector checks whether a vehicle is overlapping it. To avoid false alarms from a single blurry frame, it requires **several frames in a row** to agree before it reports a change. This is called *debouncing*.

When the status of a spot changes (e.g., a car just parked or just left), the detector sends a small update message to the backend server.

Optional **ByteTrack** mode (`--track`) also assigns a persistent ID to each vehicle across frames. If a car inside a slot starts moving its position — the detector flags it as "soon" immediately, before it has even fully left.

### 2 — The Backend (the brain)

A lightweight Python web server (FastAPI) that:

- Receives updates from the detector (`POST /spots`)
- Remembers the current status of every spot (in memory, fast)
- Saves every status change to a database file (SQLite) so nothing is lost on restart
- Logs the full history of every spot's state — used to calculate typical parking durations
- Pushes updates to every open browser tab the instant something changes, using **WebSocket** (a persistent connection, like a phone call rather than sending letters back and forth)
- Also runs a built-in **simulator** during development, so you can see the map working without a real camera

The backend also exposes a `/spots/{id}/dwell` endpoint that returns statistics about how long cars typically park in a given spot (mean, standard deviation) — the foundation of the dwell-time "soon" prediction.

### 3 — The Frontend (what you see)

A web application built with React that shows a **MapLibre GL** interactive map (free, open-source, runs in any browser). It:

- Loads the current state of all spots on first visit
- Maintains a live WebSocket connection to the backend so it receives updates instantly
- Shows a coloured SVG pin for each spot
- When you click a pin: shows the spot ID, current status, and a "Navigate" link that opens Google Maps directions to that exact spot
- Has a dark/light theme toggle
- Shows a red "Offline" pill in the corner if the connection to the backend is lost, and automatically reconnects with exponential back-off (waits 1 s, then 2 s, then 4 s… up to 30 s between attempts)

---

## Data flow — step by step

Here is exactly what happens when a car parks in spot A1:

```
1. Camera captures a frame.
2. YOLO11 finds a car bounding box in the frame.
3. The detector checks: does this box overlap slot A1 by enough? → Yes.
4. Three frames in a row agree → debounce confirmed.
5. Detector sends:  POST /spots  { id:"A1", status:"occupied", lat:..., lng:... }
6. Backend stores A1=occupied in memory.
7. Backend appends a row to spot_history (timestamp + status) in SQLite.
8. Backend broadcasts  { type:"spot.update", payload: A1 }  over WebSocket.
9. Every open browser tab receives the message.
10. The A1 pin on the map turns red.
```

And when it looks like the car is leaving:

```
(ByteTrack mode)
11. Detector notices A1's vehicle track has moved 20+ pixels in 10 frames.
12. Detector sends:  POST /spots  { id:"A1", status:"soon" }
13. A1 pin turns yellow — driver nearby knows to head there.

(or via dwell-time, no camera motion needed)
11. Backend dwell-checker runs every 15 s.
12. A1 has been occupied for 70 % of its historical mean dwell time.
13. Backend promotes A1 → "soon" and broadcasts the update.
14. A1 pin turns yellow.
```

---

## Architecture diagram

```mermaid
flowchart LR
    subgraph input ["Video Input"]
        Cam["📷 Network camera / RTSP stream"]
        File["🎬 Video file (e.g. PKLot dataset)"]
        Web["💻 Webcam"]
    end

    subgraph detector ["Detector  (detector/)"]
        Src["source.py\nOpenCV frame reader"]
        Inf["inference.py\nYOLO11 + IoU occupancy\n+ ByteTrack motion"]
        Track["tracker.py\nMotionMonitor\ncentroid history"]
    end

    subgraph backend ["Backend  (backend/)"]
        API["main.py\nFastAPI routes"]
        Store["store.py\nIn-memory spot state"]
        DB["db.py\nSQLite  ·  parking.db\ncurrent state + full history"]
        Dwell["dwell_checker_loop\n'soon' via history stats"]
    end

    subgraph frontend ["Frontend  (frontend/)"]
        WS["SpotsProvider\nWebSocket client\nauto-reconnect"]
        Map["ParkingMap\nMapLibre GL"]
        Pins["MapMarkers\nSVG pins + popup"]
    end

    Cam & File & Web --> Src --> Inf
    Inf <--> Track
    Inf -->|"POST /spots"| API
    API --> Store --> DB
    DB --> Dwell --> API
    API -->|"WebSocket broadcast"| WS
    WS --> Pins --> Map
```

---

## Getting started

You need **Python 3.10+** and **Node.js 20+** installed.

### Step 1 — Start the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API is now running at `http://127.0.0.1:8000`.
It starts a simulator that randomly cycles spot statuses every 2 seconds — useful for testing without a real camera.

### Step 2 — Start the frontend

**Standard (local drive):**
```bash
cd frontend
npm install
cp ENV_EXAMPLE.txt .env
# Open .env and add your free MapTiler key from https://maptiler.com
npm run dev
```

**Google Drive / OneDrive (Windows only):**
```powershell
cd frontend
# First run: copy ENV_EXAMPLE.txt to .env and add your MapTiler key
.\dev.ps1
```

> `dev.ps1` installs npm packages to `%LOCALAPPDATA%\ParkingSpotter\frontend\` instead of the project folder. This is needed because npm cannot write files reliably on virtual/cloud-synced drives (Google Drive, OneDrive). The script also copies `@types/react` into the local project folder so your code editor (Cursor / VS Code) can find TypeScript types without needing a full local install.

Open `http://localhost:5173` in your browser. You should see a map with coloured pins cycling through states (that's the simulator).

### Step 3 — Run the real detector *(optional)*

The detector is only needed when you want to connect a real camera. The simulator in the backend is enough for UI development and demos.

```bash
cd detector
pip install -r requirements.txt

# First: draw your parking slot polygons on a video frame (one-time setup)
python draw_slots.py --source sample.mp4
# Click the corners of each slot → Enter → type ID + lat/lng → repeat → Q to save

# Then run the detector
python -m detector.main --source sample.mp4 --preview           # video file, show annotated window
python -m detector.main --source 0 --preview                    # webcam
python -m detector.main --source rtsp://192.168.1.10/stream     # network camera

# With ByteTrack motion detection enabled:
python -m detector.main --source sample.mp4 --track --preview
```

When the detector is running, set `SIMULATOR=false` in the backend environment so the random simulator doesn't interfere.

---

## Folder layout

```
Smart-Parking-Detector/
│
├── backend/                    ← Python web server
│   ├── app/
│   │   ├── main.py             ← Routes, simulator, dwell-checker, app factory
│   │   ├── models.py           ← Data shapes (Spot, Event) using Pydantic
│   │   ├── store.py            ← Fast in-memory spot state + SQLite write-through
│   │   ├── hub.py              ← WebSocket broadcast hub (sends to all browsers)
│   │   └── db.py               ← Database setup; dwell-time query helpers
│   └── requirements.txt
│
├── detector/                   ← Python camera AI service
│   ├── detector/
│   │   ├── main.py             ← CLI entry point
│   │   ├── config.py           ← Reads slots.json config file
│   │   ├── source.py           ← Video stream reader (OpenCV)
│   │   ├── inference.py        ← YOLO11 detection + IoU occupancy + ByteTrack mode
│   │   └── tracker.py          ← MotionMonitor: centroid history for motion "soon"
│   ├── draw_slots.py           ← Interactive tool to draw slot polygons on a frame
│   ├── slots.example.json      ← Example slot config template
│   └── requirements.txt
│
├── frontend/                   ← React web app
│   ├── src/
│   │   ├── components/         ← ParkingMap, MapMarkers, ThemeProvider
│   │   ├── state/              ← SpotsProvider: WebSocket client + spot state
│   │   ├── lib/                ← api.ts: HTTP fetch + reconnecting WS controller
│   │   └── types.ts            ← Shared TypeScript types
│   ├── dev.ps1                 ← Windows launcher for cloud-synced drives
│   ├── vite.launcher.config.ts ← Vite config used when running from AppData
│   ├── ENV_EXAMPLE.txt         ← Copy to .env and fill in your API keys
│   └── package.json
│
├── Description/                ← Reference assets (design PDFs, images)
├── .gdriveignore               ← Tells Google Drive to skip node_modules, .db files, etc.
├── docker-compose.yml          ← Docker setup skeleton (backend + frontend + detector)
└── README.md
```

---

## Configuration reference

### Frontend — `frontend/.env`

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_MAPTILER_KEY` | *(required)* | Free API key from [maptiler.com](https://maptiler.com) — used to load the map tiles |
| `VITE_API_URL` | `http://127.0.0.1:8000` | Where the backend is running |

### Backend — environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SIMULATOR` | `true` | Set to `false` when a real detector is running |
| `DB_PATH` | `parking.db` | Path to the SQLite database file |
| `CORS_ORIGINS` | `http://localhost:5173,...` | Comma-separated list of allowed browser origins |
| `SOON_THRESHOLD` | `0.7` | Fraction of mean dwell time after which a spot turns yellow (0.7 = 70 %) |
| `DWELL_MIN_COUNT` | `3` | Minimum number of historical dwell samples needed before predictions activate |
| `DWELL_CHECK_INTERVAL` | `15.0` | How often (seconds) the dwell-checker runs |

### Detector — CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `0` | Video source: webcam index (`0`), file path, or `rtsp://` URL |
| `--config` | `slots.json` | Path to your slot polygon config file |
| `--model` | `yolo11n.pt` | AI model to use. `n` = nano (fast), `s`/`m`/`l` = larger/more accurate |
| `--iou` | `0.25` | How much overlap (0–1) between a vehicle and a slot counts as occupied |
| `--debounce` | `3` | Frames in a row that must agree before a status change is published |
| `--skip` | `2` | Process every N-th frame (higher = faster, lower = more responsive) |
| `--preview` | off | Open a window showing the video with coloured slot overlays |
| `--track` | off | Enable ByteTrack — adds motion-based "soon" detection |
| `--motion-px` | `15.0` | How many pixels a vehicle must move (over the window) to be flagged as leaving |
| `--motion-frames` | `10` | How many frames of centroid history to compare against |

**Tuning `--track` mode:** lower `--motion-px` = more sensitive but more false positives from camera vibration. Start with `--motion-px 20 --motion-frames 8` for a 15–25 fps camera.

---

## API reference

The backend exposes these HTTP endpoints (also browsable at `http://127.0.0.1:8000/docs`):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"ok": true}` — useful to check if the server is up |
| `GET` | `/spots` | Returns the current status of all parking spots as a JSON array |
| `POST` | `/spots` | Update or create a spot (used by the detector) |
| `GET` | `/spots/{id}/dwell` | Returns historical dwell-time stats for one spot: `{count, mean, stddev}` in seconds |
| `WS` | `/ws` | WebSocket connection — the frontend subscribes here for live updates |

---

## Review-driven priorities

The April 2026 cross-model review converged on these decisions:

- Keep the current three-service architecture. This is a hardening-and-scale project, not a rewrite project.
- Secure detector ingest first: `POST /spots` needs request authentication before any production exposure.
- Fix correctness before adding new model families: the dwell-time session logic and SQLite upsert behavior need cleanup first.
- Keep `react-map-gl/maplibre`; it is actively used by the map components.
- Keep detector ingest on HTTP for now. Revisit MQTT/NATS only when multi-camera fan-in or deployment load proves it is necessary.
- Optimize the existing YOLO11 + ByteTrack path before experimenting with YOLO12, RF-DETR, or other detector swaps.
- Treat Gemma / VLM work as optional, event-triggered adjunct functionality, never as the hot-path occupancy engine.

## Consensus roadmap

| Priority | Focus | Winning direction |
|----------|-------|-------------------|
| `P0` | Security + correctness | Add authenticated detector ingest, align dwell-session logic, and add a minimal automated test suite |
| `P1` | Deployment truth + Phase 5 | Create real Dockerfiles/healthchecks, fix SQLite coordinate upserts, and build multi-camera + homography support |
| `P2` | Scale prep + measured experiments | Add CI, clean up detector configuration ownership, seed better dwell demos, and fine-tune YOLO11 on parking data |
| `P3` | Conditional infrastructure / R&D | Add MQTT/NATS only if actual load requires it; keep VLM features off the critical path |

---

## Technology choices — why these tools?

| Component | Choice | Why |
|-----------|--------|-----|
| Map library | MapLibre GL + MapTiler | Open-source, no vendor lock-in, free tier covers 100k map loads/month |
| React map bindings | `react-map-gl/maplibre` | Already in active use in the frontend; keep it unless the map layer is deliberately rewritten |
| AI detection model | YOLO11n (Ultralytics) | Fast enough for the current CPU-first MVP; the next recommended step is parking-lot fine-tuning, not a detector-family swap |
| Vehicle tracking | ByteTrack (built into Ultralytics) | Simple, fast, no extra dependencies — built for exactly this kind of fixed-camera scenario |
| Occupancy logic | Per-slot IoU (overlap ratio) | More reliable than pixel-counting for varied car sizes and angles |
| Detector transport | HTTP `POST /spots` now | Good enough for the current MVP; message-bus complexity should wait until real multi-camera load appears |
| Backend framework | FastAPI (Python) | Async, WebSocket-native, auto-generates API docs at `/docs` |
| Database | SQLite (aiosqlite) | Zero setup, survives process restarts, history table enables dwell-time prediction |
| Frontend framework | React 19 + TypeScript + Vite | Modern, fast, type-safe |
| Styling | Tailwind CSS v4 | Utility-first, small bundle, easy dark mode |
| VLM / adjunct AI | Event-triggered assistant only | Useful later for summaries, privacy workflows, or operator assist, but not for per-frame occupancy decisions |

---

## Prior work

The original prototype (Leaflet map + vanilla JS) and the first React/Mapbox version are preserved on the [`v1`](../../tree/v1) branch for reference.

---

## License

MIT — see [`LICENSE`](LICENSE).
