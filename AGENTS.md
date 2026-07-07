# ParkingSpotter — Agent Guide

Authoritative guide for AI agents (and humans) making changes in this repo.
Read this file before writing code. Detailed references:

- [`todo.md`](todo.md) — the execution roadmap (April 2026 consensus items, all complete, plus the July 2026 `R0`–`R3` readiness push). **Work from it; do not re-litigate architecture.**
- [`docs/MODEL-ROUTING.md`](docs/MODEL-ROUTING.md) — which model tier to use for which task: dev-agent routing *and* runtime CV model routing.
- [`docs/PROJECT-REVIEW-2026-07.md`](docs/PROJECT-REVIEW-2026-07.md) — the July 2026 independent review: findings, evidence, and the readiness gap. The `R0`–`R3` items derive from it.
- [`README.md`](README.md) — product description, deployment baseline, API reference.

## What this project is

Real-time parking availability: **detector** (YOLO11 + ByteTrack on a camera
stream) → **backend** (FastAPI + SQLite + WebSocket) → **frontend** (React +
MapLibre map). The differentiating product signal is the yellow **"soon"**
state (dwell-time prediction + motion detection).

Current stage: a hardened pilot-ready codebase that **has never been validated
against a real camera**. The strategic priority is contact with reality
(`R1` pilot), not new surfaces. When in doubt between adding a feature and
making an existing path measurable, choose measurable.

## Architecture guardrails (do not violate)

The April 2026 guardrails still hold, extended by the July 2026 review:

1. **Keep the three-service shape** `detector -> backend -> frontend`. No rewrites, no transport swaps.
2. **Benchmarks or it didn't happen.** Any proposal to change detector family, model size, framework, or transport must cite measured results from `detector/benchmark.py` on labeled parking footage *from this repo's pilots*. Release notes, blog posts, and leaderboard numbers do not count.
3. **Detection hot path stays YOLO11-family + ByteTrack.** Fine-tune before any family swap (`R2.1`).
4. **VLMs (Gemma etc.) are event-triggered adjuncts only.** Never in the per-frame occupancy loop.
5. **Browser-driven detection is demo/authoring-only.** The hybrid view posting frames to `detector/detector/server.py` exists for slot authoring and demos. Production detection is headless `python -m detector.main` reading RTSP. Do not grow the browser path into a parallel production pipeline.
6. **Demo freeze.** `HybridStreetMapView.tsx` and `SimulationView.tsx` get bug fixes only — no new features — until the `R1.2` pilot produces accuracy metrics. The demo layer already exceeds the detection core in line count; do not widen that gap.
7. **HTTP ingest stays.** No MQTT/NATS until measured multi-camera load justifies it.
8. **Keep `react-map-gl/maplibre`.** It is actively used.
9. **Single-process backend.** In-memory `SpotStore` + `Hub` assume exactly one uvicorn worker. Never suggest `--workers N>1`; never add features that assume state is shared across processes. If one process stops being enough, that is a roadmap discussion, not a quick fix.
10. **One geometry implementation.** IoU/coverage math and pixel→lat/lng calibration belong in Python (detector service). The frontend consumes results via API. Do not (re)implement calibration math in TypeScript — the existing TS inverse-distance-weighting copy is scheduled for removal in `R1.3`, not a pattern to extend.
11. **Every new write endpoint ships with auth and size limits** in the same PR. `POST /spots` HMAC is the reference pattern. (The projects API retrofit is `R0.1`.)

## Development process

1. **Spec first.** Every roadmap item follows the `todo.md` format: *Goal / Likely files / Required implementation / Acceptance criteria / Progress checkboxes*. If you are asked to do work that has no spec, write the spec into `todo.md` first (or propose it) — this format is the contract that makes implementation safe.
2. **Implement additively, with tests.** Any schema or API change updates the relevant docs (`README.md`, service READMEs) in the same task. Prefer pure-function tests; tests must run without a camera, GPU, or model downloads.
3. **Run the verification gate** (below) before claiming an item done. Report actual output, not intentions.
4. **Independent verification pass.** After a batch of roadmap items merges, a *different* model than the implementer reviews the diff against the acceptance criteria (see `docs/MODEL-ROUTING.md`). Verifiers must run the suite themselves before filing findings — the April 2026 corrections pass ([`Corrections from Opus 4.7, Apr 22.md`](Corrections%20from%20Opus%204.7,%20Apr%2022.md)) is the model to follow.
5. **Done means done**: implementation merged, tests cover the new behavior, docs updated, guardrails respected, progress checkboxes ticked in `todo.md`.

## Verification gate

Run from the repo root before marking any item complete:

```bash
python -m pytest                 # backend + detector tests (~20+, no GPU/weights needed)
cd frontend
npm run lint
npm run build
```

CI (`.github/workflows/ci.yml`) runs the same on push/PR. If you add a test
that needs torch/YOLO weights, it must be skipped in CI (`detector/requirements-ci.txt`
deliberately excludes them).

## Security invariants

- `POST /spots` is HMAC-authenticated: signature input `timestamp + "." + raw_body`, HMAC-SHA256, constant-time compare, replay window via `PARKINGSPOTTER_MAX_SIGNATURE_AGE_SECONDS`. Never weaken or bypass this.
- No secrets in git. `PARKINGSPOTTER_SHARED_SECRET` and keys come from the environment; compose files may carry clearly-labeled dev placeholders only.
- The backend stores spot status metadata — never raw video frames or license plates. Keep it that way; privacy posture is documented in the README.
- Uploads (projects API) must enforce extension allowlists, path-traversal guards, and size caps (`R0.1` completes this).

## Repo map

```
backend/app/        FastAPI: main (routes/loops), store (canonical+observations),
                    merge (multi-camera rules), db (SQLite+dwell sessions),
                    hub (WS broadcast), auth (HMAC), project_store/project_models
backend/tests/      pytest suite (auth, dwell, merge, upsert, projects, seeds)
detector/detector/  main (CLI), inference (YOLO+occupancy), tracker (motion),
                    server (HTTP detect for hybrid view), source, config, auth,
                    street_calibration
detector/           draw_slots.py, calibration.py, benchmark.py, fine_tune_yolo11.py
frontend/src/       App, components/ (ParkingMap, MapMarkers, HybridStreetMapView,
                    SimulationView), state/SpotsProvider, lib/api.ts
todo.md             Roadmap (prescriptive specs; agents execute from here)
docs/               Model routing, project reviews
```

## Commands

```bash
# Backend (http://127.0.0.1:8000, simulator on by default)
cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload

# Frontend (http://localhost:5173; needs .env with VITE_MAPTILER_KEY)
cd frontend && npm install && npm run dev

# Detector (headless, real path)
cd detector && python -m detector.main --source <file|rtsp|index> [--track --preview]

# Detector HTTP service (demo/authoring path for the hybrid view)
cd detector && python -m detector.server --model yolo11n.pt --port 8010

# Full stack via Docker
docker compose up backend frontend
```

## Current priorities

Execute in order from `todo.md` § *July 2026 roadmap (R0–R3)*:

| Phase | Theme | Items |
|-------|-------|-------|
| `R0` | Ship safely what's in flight | Secure projects API; SQLite WAL + history retention; "soon" lifecycle correctness |
| `R1` | Contact with reality | Occupancy metric v2 (polygon coverage); real-camera pilot with labeled benchmark; single geometry implementation |
| `R2` | Measured improvement | YOLO11 fine-tune vs per-slot patch classifier head-to-head; time-bucketed dwell; decompose `HybridStreetMapView` |
| `R3` | Product layer (deferred) | Multi-lot model, operator dashboard, PWA, observability |

Do not start `R2`/`R3` items while `R0`/`R1` items remain open, unless the user
explicitly reprioritizes.
