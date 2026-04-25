# ParkingSpotter — Detector

Python service that reads a video stream (webcam, file, or RTSP), runs YOLO11 vehicle detection, determines whether each defined parking slot is occupied, and pushes status updates to the backend via `POST /spots`.

## Stack

- **Ultralytics YOLO11** — vehicle detection (COCO classes: car, truck, bus, motorcycle)
- **OpenCV** — video capture and frame processing
- **httpx** — synchronous HTTP client for posting to the backend
- **NumPy** — IoU computation

## Setup

```bash
cd detector
pip install -r requirements.txt
```

For **CI-style** installs (unit tests only, no Ultralytics/torch), use `pip install -r requirements-ci.txt` together with backend test dependencies — see the repo root `pyproject.toml` and `.github/workflows/ci.yml`.

> YOLO11 weights (`yolo11n.pt`) are downloaded automatically on first run from the Ultralytics CDN.
> For CPU-only machines the nano (`n`) or small (`s`) variant is recommended.

## Detector authentication

The detector now signs every `POST /spots` request with HMAC-SHA256.

Before running the detector, set the same shared secret in both the backend and detector environments:

```powershell
$env:PARKINGSPOTTER_SHARED_SECRET="change-me"
```

```bash
export PARKINGSPOTTER_SHARED_SECRET="change-me"
```

Headers sent on each update:

- `X-ParkingSpotter-Timestamp`
- `X-ParkingSpotter-Signature`

The signature is computed over `timestamp + "." + raw_body`.
If `PARKINGSPOTTER_SHARED_SECRET` is missing, the detector exits instead of sending unsigned updates.

## Slot configuration

Create a `slots.json` file (copy `slots.example.json` as a starting point).

```json
{
  "camera_id": "cam_1",
  "slots": [
    {
      "id": "A1",
      "lat": 47.62319,
      "lng": -122.35460,
      "polygon": [[100, 310], [195, 310], [195, 420], [100, 420]]
    }
  ]
}
```

### Field reference

| Field | Description |
|-------|-------------|
| `camera_id` | Identifier sent to the backend with every update |
| `slots[].id` | Spot ID — must match the IDs the frontend and backend expect |
| `slots[].lat` / `lng` | Geographic coordinates for the map pin |
| `slots[].polygon` | List of `[x, y]` pixel coordinates in the camera frame |

Backend base URL is **not** part of the long-term slot file contract. Use `--backend-url` or `PARKINGSPOTTER_BACKEND_URL` when running the detector. A legacy `backend_url` key in JSON is still read if present.

### How to get polygon coordinates — draw_slots tool

Use the interactive polygon drawing tool instead of guessing pixel coordinates manually:

```bash
# Draw slots on frame 0 of a video file
python draw_slots.py --source parking.mp4

# Resume editing an existing slots.json (loads it, lets you add more)
python draw_slots.py --source parking.mp4 --config slots.json

# Use a specific frame number as the background
python draw_slots.py --source parking.mp4 --frame 120
```

**Controls inside the window:**

| Key | Action |
|-----|--------|
| Left-click | Add vertex to current polygon |
| Right-click / U | Undo last vertex |
| Enter / N | Finish slot → prompted for ID, lat, lng in terminal |
| R | Reset / discard current polygon |
| D (×2) | Delete last completed slot (confirm on second press) |
| S | Save without quitting |
| Q / Esc | Save and quit |
| ← / → | Step one frame back / forward (video files only) |

All completed slots are shown in green; the polygon being drawn is shown in blue.  
The tool reads an existing `slots.json` on startup (if `--config` or `--output` already exists) so you can incrementally add slots across sessions.

### Homography calibration (auto lat/lng)

For multi-camera / Phase 5 workflows, you can avoid typing lat/lng for every slot by supplying a calibration file with **four or more** reference pairs: pixel `[x, y]` in the **same frame** you use for drawing (see `--frame`) and the corresponding WGS84 `lat` / `lng`.

1. Copy `calibration.example.json` and replace the sample points with real landmarks you can identify on the frame and on a map.
2. Run:

```bash
python draw_slots.py --source parking.mp4 --frame 0 --calibration my_calibration.json
```

3. When you finish a polygon, the tool only asks for the **slot ID**; `lat` / `lng` are taken from the **pixel centroid** of the polygon through the homography (local tangent plane + `cv2.findHomography`).

Keep `camera_id` in the calibration JSON aligned with the slot file and detector (`PARKINGSPOTTER_*` / `slots.json`). Manual lat/lng entry is unchanged if you omit `--calibration`.

## Run

```bash
# Webcam (index 0)
python -m detector.main --source 0

# Local video file
python -m detector.main --source /path/to/parking.mp4

# RTSP stream
python -m detector.main --source rtsp://192.168.1.10/stream

# Show annotated window (press q to quit)
python -m detector.main --source 0 --preview
```

### Serve YOLO boxes for the hybrid/3D UI

The frontend's hybrid street/map view and synthetic 3D scene can send screenshots
or sampled video frames to a local detector HTTP service. Start it before using
the top-pane detection controls:

```powershell
cd detector
pip install -r requirements.txt
$env:PARKINGSPOTTER_SHARED_SECRET="change-me"  # same value as backend, required for /spots/sync
python -m detector.server --model yolo11n.pt --port 8010
```

The service exposes:

- `GET /health`
- `POST /detect?conf=0.2&include_people=true` with a raw JPEG/PNG/WebP body, returning people/vehicle boxes in image pixels
- `POST /geometry/lines` with a raw image body, returning experimental Hough line segments for curbs/buildings/pavement edges
- `POST /spots/sync` with calibrated slot statuses, signing and forwarding them to the backend `/spots` endpoint

### Street calibration JSON

Use `street_calibration.example.json` as the starting point for fixed street
screenshots or stable video. The same pixel coordinate system is used for anchor
points and parking-slot polygons:

```json
{
  "camera_id": "first_ave_fixed_view",
  "frame_size": [1920, 1080],
  "reference_points": [
    { "pixel": [312, 214], "lat": 47.62294, "lng": -122.35236 }
  ],
  "parking_slots": [
    {
      "id": "1ST-01",
      "lat": 47.62238,
      "lng": -122.35228,
      "polygon": [[432, 692], [722, 664], [816, 806], [486, 854]]
    }
  ]
}
```

Reference points should be stationary landmarks visible in both the image/video
and the 2D map: building corners, intersections, curb corners, or lane edges.

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `0` | Webcam index, file path, or RTSP URL |
| `--config` | `slots.json` | Path to slot config JSON |
| `--backend-url` | — | Backend base URL (overrides env and legacy JSON) |
| `--model` | `yolo11n.pt` | Ultralytics model name or local `.pt` path |
| `--iou` | `0.25` | IoU threshold to classify a slot as occupied |
| `--debounce` | `3` | Consecutive frames required to confirm a change |
| `--skip` | `2` | Process every N-th frame (reduces CPU load) |
| `--preview` | off | Show annotated video window |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PARKINGSPOTTER_BACKEND_URL` | `http://127.0.0.1:8000` | Backend base URL when `--backend-url` is not set |
| `PARKINGSPOTTER_SHARED_SECRET` | *(required)* | Shared secret used to sign detector updates sent to the backend |

## Docker

```bash
docker compose --profile detector up
```

The detector image includes a bundled sample video and default `slots.json` so the optional Compose profile can start without a physical camera.
For a real deployment, override the detector command with your actual source and slot configuration.

## Tests

```bash
python -m pytest tests
```

Current detector tests avoid real cameras, GPUs, and model downloads by stubbing the YOLO dependency and checking:

- slot-overlap threshold behavior
- debounce-driven status transitions

## Benchmarking YOLO11 on real or public footage

Use `benchmark.py` to measure the current YOLO11 baseline before fine-tuning or
trying another detector family. Start with PKLot frames or still frames sampled
from a pilot camera, plus a `slots.json` drawn for those frames.

```bash
python benchmark.py --frames-dir ./benchmark_frames --config slots.json --model yolo11n.pt
```

For accuracy metrics, add JSON Lines labels:

```json
{"image":"frame001.jpg","spots":{"A1":"occupied","A2":"available"}}
```

Then run:

```bash
python benchmark.py --frames-dir ./benchmark_frames --config slots.json --labels labels.jsonl --output report.json
```

The report includes mean/median latency, FPS, status counts, and binary
occupied-vs-not-occupied precision/recall/accuracy. `soon` is treated as
occupied for benchmark metrics.

### Fine-tuning workflow

Fine-tune only after saving a baseline report on the exact validation frames you
will use for comparison. Prepare an Ultralytics dataset YAML from PKLot or pilot
camera labels; `parking_dataset.example.yaml` shows the expected shape.

```bash
python fine_tune_yolo11.py --data parking_dataset.yaml --model yolo11n.pt --epochs 50 --output train-summary.json
```

Then benchmark the tuned weights against the same labeled frames:

```bash
python benchmark.py --frames-dir ./benchmark_frames --config slots.json --labels labels.jsonl --model yolo11n.pt --output reports/yolo11n-baseline.json
python benchmark.py --frames-dir ./benchmark_frames --config slots.json --labels labels.jsonl --model runs/parking-spotter/yolo11-parking/weights/best.pt --output reports/yolo11n-parking-tuned.json
```

Use `benchmark_report.example.json` as the comparison report template. Do not
switch detector families unless the tuned YOLO11 result still misses the agreed
precision/recall/latency target.

## How occupancy works

```
For each frame:
  1. YOLO11 detects all vehicles → bounding boxes
  2. For each slot polygon → compute IoU with every vehicle bbox
  3. If any IoU ≥ threshold → OCCUPIED, else AVAILABLE
  4. Debounce: status only changes after `debounce` consecutive frames agree
  5. On confirmed change → POST /spots to backend
```

IoU (Intersection over Union) measures the overlap between the slot's
bounding rectangle and a detected vehicle's bounding box. A threshold of 0.25
works well for angled cameras; lower it for overhead views.

## Module layout

```
detector/
├── draw_slots.py          # Interactive polygon drawing tool (run directly)
├── detector/
│   ├── main.py            # CLI entry point (argparse, loop, HTTP posts)
│   ├── config.py          # SlotConfig / CameraConfig dataclasses + JSON loader
│   ├── server.py          # Local HTTP detector for browser image/video frames
│   ├── street_calibration.py # Fixed street-view calibration schema
│   ├── source.py          # VideoSource: OpenCV VideoCapture wrapper
│   └── inference.py       # OccupancyDetector: YOLO11 + per-slot IoU + debounce
├── slots.example.json     # Template slot config
└── street_calibration.example.json
```

## Datasets for testing without a real camera

- **PKLot** — overhead parking lot images with occupancy labels
  `https://web.inf.ufpr.br/vri/databases/parking-lot-database/`
- Any dashcam or security camera footage of a parking area
