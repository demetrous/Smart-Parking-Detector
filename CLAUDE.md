# CLAUDE.md

Read [`AGENTS.md`](AGENTS.md) first — it is the authoritative agent guide for
this repo (guardrails, development process, verification gate, priorities).

Quick facts:

- Three services: `detector/` (YOLO11 + ByteTrack) → `backend/` (FastAPI + SQLite + WS) → `frontend/` (React + MapLibre). Do not restructure.
- Work from the prescriptive specs in [`todo.md`](todo.md); current phase is the July 2026 `R0`–`R3` readiness push. Model-tier selection lives in [`docs/MODEL-ROUTING.md`](docs/MODEL-ROUTING.md).
- Verification gate before claiming anything done, from repo root:
  - `python -m pytest` (must pass without GPU, camera, or YOLO weights)
  - `cd frontend && npm run lint && npm run build`
- Backend is single-process by design (in-memory store + WS hub). Never suggest multiple uvicorn workers.
- `POST /spots` HMAC auth is a security invariant — never weaken it. New write endpoints need auth + size limits in the same PR.
- Browser-driven detection (hybrid view → `detector.server`) is demo-only; production detection is headless `detector.main` on RTSP.
- Demo freeze: no new features in `HybridStreetMapView.tsx` / `SimulationView.tsx` until the real-camera pilot (`R1.2`) has produced accuracy metrics.
