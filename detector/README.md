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

> YOLO11 weights (`yolo11n.pt`) are downloaded automatically on first run from the Ultralytics CDN.
> For CPU-only machines the nano (`n`) or small (`s`) variant is recommended.

## Slot configuration

Create a `slots.json` file (copy `slots.example.json` as a starting point).

```json
{
  "camera_id": "cam_1",
  "backend_url": "http://127.0.0.1:8000",
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
| `backend_url` | Base URL of the running backend |
| `slots[].id` | Spot ID — must match the IDs the frontend and backend expect |
| `slots[].lat` / `lng` | Geographic coordinates for the map pin |
| `slots[].polygon` | List of `[x, y]` pixel coordinates in the camera frame |

### How to get polygon coordinates

1. Open your camera feed (or a recorded frame) in any image viewer.
2. Note the pixel corners of each parking slot.
3. Enter them as a 4-point (or more) polygon in `slots.json`.

You can also use the `--preview` flag to see the annotated bounding boxes overlaid on the live feed.

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

## CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `--source` | `0` | Webcam index, file path, or RTSP URL |
| `--config` | `slots.json` | Path to slot config JSON |
| `--model` | `yolo11n.pt` | Ultralytics model name or local `.pt` path |
| `--iou` | `0.25` | IoU threshold to classify a slot as occupied |
| `--debounce` | `3` | Consecutive frames required to confirm a change |
| `--skip` | `2` | Process every N-th frame (reduces CPU load) |
| `--preview` | off | Show annotated video window |

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
├── main.py       # CLI entry point (argparse, loop, HTTP posts)
├── config.py     # SlotConfig / CameraConfig dataclasses + JSON loader
├── source.py     # VideoSource: OpenCV VideoCapture wrapper
└── inference.py  # OccupancyDetector: YOLO11 + per-slot IoU + debounce
```

## Datasets for testing without a real camera

- **PKLot** — overhead parking lot images with occupancy labels
  `https://web.inf.ufpr.br/vri/databases/parking-lot-database/`
- Any dashcam or security camera footage of a parking area
