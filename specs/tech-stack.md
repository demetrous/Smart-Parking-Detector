# Tech stack

Three services, one direction of data flow. Do not restructure.

```
camera / RTSP → detector → POST /spots (HMAC) → backend → WebSocket → frontend
```

| Service | Stack | Notes |
|---------|-------|-------|
| `detector/` | Python, Ultralytics YOLO11 (PyTorch), ByteTrack, OpenCV (video I/O, calibration, drawing), httpx, numpy | Production path is headless `python -m detector.main` on RTSP. `detector.server` (HTTP detect for the hybrid view) is demo/authoring only. |
| `backend/` | Python, FastAPI, uvicorn, pydantic, aiosqlite (SQLite), WebSocket hub | **Single process by design**: in-memory `SpotStore` + `Hub`. Never run more than one uvicorn worker. |
| `frontend/` | React 19, TypeScript, Vite, Tailwind 4, MapLibre via `react-map-gl/maplibre`, three.js (simulation view) | Consumes results via API; no geometry or calibration math in TypeScript. |

## Hard constraints

These come from `AGENTS.md` (the authoritative guide) and bind every spec.

- Detection hot path stays YOLO11-family + ByteTrack. Fine-tune before any
  family swap.
- HTTP ingest stays; no MQTT/NATS until measured multi-camera load justifies it.
- `POST /spots` HMAC (timestamp + "." + raw body, HMAC-SHA256, constant-time
  compare, replay window) is a security invariant. Never weaken it.
- One geometry implementation, in Python.
- VLMs are event-triggered adjuncts only.
- No new dependencies without the owner's approval; say so in the spec's
  Decisions section when one is proposed.

## Dependency notes

- `opencv-python` is pinned `<5`. Upgrade only in a deliberate PR that passes
  the gate and re-runs the benchmark on 5.x. Use the GUI build locally,
  `opencv-python-headless` only in CI and Docker.
- CI installs `detector/requirements-ci.txt`, which deliberately excludes
  torch and YOLO weights. Tests that need them must be skipped in CI.

## Verification gate

Run from the repo root before calling any phase done:

```bash
python -m pytest            # must pass without GPU, camera, or YOLO weights
cd frontend && npm run lint && npm run build
```

CI (`.github/workflows/ci.yml`) runs the same on every push and PR.

## Where to look

- `AGENTS.md`: guardrails, development process, repo map, commands.
- `README.md`: product description, deployment baseline, API reference.
- `todo.md`: the detailed July 2026 specs (R0–R3) that roadmap phases draw from.
- `docs/MODEL-ROUTING.md`: which model tier and effort to use for which task.
