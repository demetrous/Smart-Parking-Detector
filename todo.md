# ParkingSpotter — Consensus Roadmap

This file is the execution roadmap distilled from the April 2026 intermediate review, extended by the July 2026 independent review (`docs/PROJECT-REVIEW-2026-07.md`). It is intentionally prescriptive so future agents can work from it without re-litigating architecture. Read `AGENTS.md` before working from this file.

## Global guardrails

- Keep the current three-service shape: `detector -> backend -> frontend`.
- Do not rewrite the stack or replace the core transport before the current MVP is hardened.
- Keep `react-map-gl/maplibre`; it is actively used in the frontend map components.
- Keep detector ingest on HTTP `POST /spots` through `P1`. Do not add MQTT/NATS unless measured multi-camera load justifies it later.
- Keep YOLO11 + ByteTrack as the baseline detector path. Fine-tune it on parking data before evaluating detector-family swaps.
- Treat Gemma / VLM ideas as optional, event-triggered adjunct features only. They must not sit on the per-frame occupancy hot path.
- Prefer additive, test-backed changes. Any schema or API change must update docs in the same task.

### Additional guardrails — July 2026 review

- Browser-driven detection (hybrid view → `detector.server`) is demo/authoring-only; production detection is headless `detector.main` on RTSP. Do not grow the browser path into a parallel pipeline.
- Demo freeze: `HybridStreetMapView.tsx` and `SimulationView.tsx` receive bug fixes only until `R1.2` produces pilot accuracy metrics.
- Single-process backend: in-memory `SpotStore` + `Hub` assume one uvicorn worker. Do not add multi-worker configs or cross-process state assumptions.
- One geometry implementation: calibration and overlap math live in Python; the frontend consumes results via API.
- Every new write endpoint ships with auth and size limits in the same change set (`POST /spots` HMAC is the reference pattern).
- Model/stack change proposals must cite `detector/benchmark.py` results on labeled footage from this repo (see `docs/MODEL-ROUTING.md`, binding process rules).

## Execution order

1. `P0.1` Secure detector ingest `Completed Apr 18, 2026`
2. `P0.2` Fix dwell-time session logic `Completed Apr 18, 2026`
3. `P0.3` Add minimal automated tests `Completed Apr 18, 2026`
4. `P1.1` Make Docker truthful `Completed Apr 18, 2026`
5. `P1.2` Fix SQLite coordinate upsert `Completed Apr 18, 2026`
6. `P1.3` Build Phase 5 multi-camera foundation `Completed Apr 18, 2026`
7. `P1.4` Clean up detector configuration ownership `Completed Apr 18, 2026`
8. `P1.5` Define the production deployment baseline `Completed Apr 18, 2026`
9. `P2.1` Add CI `Completed Apr 18, 2026`
10. `P2.3` Improve non-production dwell demos `Completed Apr 18, 2026`
11. `P2.2` Detector benchmark + YOLO11 fine-tuning workflow `Completed Apr 24, 2026`
12. `P3.3` Pilot product-layer endpoints `Completed Apr 24, 2026`
13. `P3.4` Synthetic 3D street simulation and live visual overlay `Completed Apr 24, 2026`
14. `R0.1` Secure the projects API — **pending**
15. `R0.2` SQLite durability + history retention — **pending**
16. `R0.3` "Soon" lifecycle correctness — **pending**
17. `R1.1` Occupancy metric v2 (polygon coverage) — **pending**
18. `R1.2` Real-camera pilot + labeled benchmark — **pending**
19. `R1.3` Single geometry implementation — **pending**
20. `R2.1` Fine-tune vs per-slot patch classifier head-to-head — pending, blocked on `R1.2`
21. `R2.2` Time-bucketed dwell statistics — pending, blocked on `R1.2`
22. `R2.3` Decompose `HybridStreetMapView.tsx` — pending
23. `R3.x` Product layer (multi-lot, dashboard, PWA, observability) — deferred

## P0 — security and correctness

### `P0.1` Authenticate `POST /spots`

**Goal**

Prevent trivial spoofing of detector updates.

**Likely files**

- `backend/app/main.py`
- `backend/app/models.py`
- `detector/detector/main.py`
- `detector/detector/config.py`
- `detector/README.md`
- `README.md`

**Required implementation**

- Add shared-secret HMAC authentication for `POST /spots`.
- Use a timestamp header plus signature header so the backend can reject replayed requests.
- Verify signatures with a constant-time compare.
- Keep `GET /health`, `GET /spots`, `GET /spots/{id}/dwell`, and `WS /ws` unchanged unless a later roadmap item says otherwise.
- Do not add a message broker as part of this task.

**Recommended contract**

- Secret source: environment variable on both detector and backend.
- Detector sends:
  - raw JSON body
  - `X-ParkingSpotter-Timestamp`
  - `X-ParkingSpotter-Signature`
- Backend signs and verifies `timestamp + "." + raw_body` with HMAC-SHA256.
- Reject missing, stale, malformed, or invalid signatures with `401` or `403`.

**Acceptance criteria**

- Valid signed detector requests still update spots successfully.
- Unsigned or incorrectly signed requests are rejected.
- Replay-window handling is covered by tests.
- The auth mechanism is documented in both root and detector docs.

**Progress**

- [x] Backend now requires signed detector `POST /spots` requests.
- [x] Detector now signs updates with `X-ParkingSpotter-Timestamp` and `X-ParkingSpotter-Signature`.
- [x] Root and detector docs now describe the shared-secret contract.
- [x] Focused backend tests cover valid, missing, invalid, and stale signatures.

### `P0.2` Align dwell-session semantics

**Goal**

Remove the correctness mismatch between `query_dwell_db()` and `occupied_since_db()`.

**Likely files**

- `backend/app/db.py`
- `backend/app/main.py`
- new backend tests

**Required implementation**

- Define one occupancy session rule and use it everywhere:
  - session starts on the first transition into `occupied` or `soon`
  - session ends on the next `available`
  - transitions between `occupied` and `soon` do not start a new session
- Move the shared interpretation into one helper instead of maintaining two subtly different rules.
- Preserve timezone-aware datetime handling.

**Acceptance criteria**

- Dwell statistics and current occupied-since calculations agree on the same session boundaries.
- A sequence like `occupied -> soon -> occupied -> available` counts as one dwell.
- Sparse-history cases still return safe empty results.

**Progress**

- [x] Dwell and occupied-since logic now share one occupancy-session parser.
- [x] A session starts on the first `occupied` or `soon`, ends on the next `available`, and does not restart on `occupied <-> soon` transitions.
- [x] Regression tests cover mixed `occupied` / `soon` sessions, open sessions, and sparse-history cases.

### `P0.3` Add a minimal automated test suite

**Goal**

Create enough coverage to make the `P0` and `P1` changes safe.

**Scope**

- Backend unit tests for:
  - signed vs unsigned `POST /spots`
  - dwell-session parsing
  - SQLite upsert behavior
- Detector unit tests for:
  - slot overlap / occupancy threshold behavior
  - debounce transitions

**Rules**

- Tests must run without a real camera, GPU, or downloaded model weights.
- Prefer pure-function or fixture-driven tests over long end-to-end flows.
- Do not build the synthetic video harness yet; that is a later item.

**Acceptance criteria**

- A contributor can run the tests locally with service-local dependencies only.
- The new auth and dwell fixes are covered before `P1` work begins.

**Progress**

- [x] Added repo-root and service-local `pytest` workflows.
- [x] Backend tests now cover detector auth, dwell-session semantics, and SQLite upsert behavior.
- [x] Detector tests now cover slot-overlap threshold behavior and debounce transitions without a real camera, GPU, or model downloads.

## P1 — deployment truth and multi-camera foundation

### `P1.1` Make Docker truthful

**Goal**

Ensure `docker-compose.yml` matches reality instead of referencing Dockerfiles that do not exist.

**Likely files**

- `docker-compose.yml`
- `backend/Dockerfile`
- `frontend/Dockerfile`
- `detector/Dockerfile`
- deployment docs

**Required implementation**

- Create the three referenced Dockerfiles.
- Remove the obsolete Compose `version` field.
- Add service healthchecks.
- Keep detector startup behind the existing optional profile.
- Mount persistent backend data cleanly.
- Document the required environment variables.

**Acceptance criteria**

- `docker compose up backend frontend` builds and starts successfully.
- `docker compose --profile detector up` also starts the detector path.
- Healthchecks reflect actual service readiness, not just process startup.

**Progress**

- [x] Created `backend/Dockerfile`, `frontend/Dockerfile`, and `detector/Dockerfile`.
- [x] Removed the obsolete Compose `version` field.
- [x] Added Compose healthchecks and persistent backend-volume wiring.
- [x] Updated root and service docs with Docker usage notes.
- [x] Ready to verify: `docker compose up backend frontend` and `docker compose --profile detector up` (run on your Docker install to confirm images and healthchecks).

### `P1.2` Fix SQLite coordinate upserts

**Goal**

Stop dropping updated `lat` and `lng` values on `spots` table conflicts.

**Likely files**

- `backend/app/db.py`
- backend tests

**Required implementation**

- Update the `ON CONFLICT(id) DO UPDATE` clause in `upsert_spot_db()` so `lat` and `lng` are refreshed alongside status, confidence, camera, and timestamp.

**Acceptance criteria**

- Reposting an existing spot with corrected coordinates persists the new coordinates.
- The behavior is covered by a regression test.

**Progress**

- [x] `upsert_spot_db()` now refreshes `lat` and `lng` during `ON CONFLICT(id) DO UPDATE`.
- [x] Regression coverage verifies coordinates change on repost and history rows still append.

### `P1.3` Build Phase 5 multi-camera support

**Goal**

Support multiple detectors and overlapping views without replacing the current transport model.

**Design decision**

- Keep HTTP ingest.
- Introduce a camera-aware observation layer instead of relying on last-writer-wins for overlapping cameras.
- Use explicit configuration-driven merge rules, not heuristics.

**Required deliverables**

1. Backend camera awareness
   - Add `GET /spots?camera=<camera_id>`.
   - Preserve `camera_id` consistently through storage and API responses.
   - Separate per-camera observations from the derived canonical spot state when multiple cameras can report the same physical spot.

2. Homography calibration
   - Add a calibration artifact per camera using 4+ known pixel-to-world reference points.
   - Convert clicked slot geometry into lat/lng automatically from that calibration.

3. Slot-authoring workflow
   - Update `draw_slots.py` to optionally consume a calibration file and auto-fill coordinates.
   - Preserve manual lat/lng entry as a fallback.

4. Overlap conflict resolution
   - Implement deterministic merge rules in config, such as camera priority per shared spot.
   - Do not rely on whichever update arrived last.

**Likely files**

- `backend/app/main.py`
- `backend/app/models.py`
- `backend/app/store.py`
- `backend/app/db.py`
- `detector/draw_slots.py`
- `detector/detector/config.py`
- new calibration tool/files under `detector/`
- docs

**Acceptance criteria**

- Two cameras can report into one backend without corrupting spot state.
- `GET /spots` returns the merged canonical view.
- `GET /spots?camera=...` returns a camera-scoped view.
- The slot-drawing workflow can generate coordinates from calibration data.

**Progress**

- [x] `spot_observations` SQLite table and persistence for per-camera `(spot_id, camera_id)` updates.
- [x] `GET /spots?camera=<camera_id>` returns that camera’s last observations only; bare `GET /spots` returns merged canonical state.
- [x] Deterministic merge via `MERGE_CONFIG_PATH` JSON (`default_priority`, `per_spot`) — see `backend/merge.example.json`.
- [x] `SpotStore` keeps canonical + observation maps; `POST /spots` with `cameraId` merges; legacy posts without `cameraId` still update canonical only.
- [x] Backend tests for merge priority and legacy ingest.
- [x] Homography calibration JSON (`detector/calibration.example.json`) + `detector/calibration.py` (pixel → WGS84 via OpenCV homography in a local tangent plane).
- [x] `draw_slots.py --calibration <file>` auto-fills `lat`/`lng` from each polygon’s pixel centroid; manual entry remains when no calibration is passed.
- [x] Detector tests for calibration loading and corner round-trip (`detector/tests/test_calibration.py`).

### `P1.4` Make detector endpoint configuration unambiguous

**Goal**

Stop mixing deployment endpoint configuration into the slot-geometry file.

**Winning direction**

- `slots.json` should describe camera identity and slot geometry only.
- Backend destination should come from CLI and/or environment, not from the geometry file.

**Required implementation**

- Add an explicit detector runtime setting for backend URL.
- Define precedence clearly: CLI flag overrides environment; environment overrides default.
- Remove backend URL ownership from the long-term `slots.json` contract.
- Keep `camera_id` in the slot config.

**Acceptance criteria**

- A deployment can repoint the detector to another backend without editing `slots.json`.
- The config contract is documented and reflected in `slots.example.json` and detector docs.

**Progress**

- [x] Detector resolves backend URL with precedence: `--backend-url` → `PARKINGSPOTTER_BACKEND_URL` → deprecated `backend_url` in JSON → `http://127.0.0.1:8000`.
- [x] `slots.example.json` and `draw_slots.py` output no longer require `backend_url`; Docker/Compose use `PARKINGSPOTTER_BACKEND_URL`.
- [x] Documented in root `README.md`, `detector/README.md`, and CLI tables.

### `P1.5` Define the production deployment baseline

**Goal**

Turn "what do we need to buy/create/run?" into an explicit deployment contract before production rollout.

**Winning direction**

- Keep the smallest production topology simple: camera -> detector -> backend/frontend.
- Support both on-prem and cloud-hosted backend/frontend deployments.
- Document the minimum required devices, services, secrets, and recurring subscriptions clearly enough that a non-author can provision them.

**Required implementation**

1. Production inventory
   - Document the minimum required hardware roles:
     - fixed camera per monitored area
     - detector compute host
     - backend/frontend host
     - operator/admin browser device
   - Document minimum expectations for camera capability, detector placement, storage persistence, and network reliability.

2. Service dependencies
   - Define the required runtime services for production:
     - HTTPS reverse proxy
     - DNS/domain when internet-facing
     - environment/secrets management
     - backup path for SQLite data
   - Keep optional services clearly labeled as optional, not mandatory.

3. Subscription dependencies
   - Document that the frontend currently depends on a MapTiler key unless map tiles are self-hosted later.
   - Distinguish demo/free-tier assumptions from production traffic assumptions.
   - Make clear which items do not require paid subscriptions today.

4. Deployment topology guidance
   - Document the smallest credible single-camera production topology.
   - Document when to separate detector and backend hosts.
   - Document when multi-camera work becomes a prerequisite instead of an enhancement.
   - Document temporary dev/test camera options such as an iPhone-published RTSP stream, while keeping fixed mounted cameras as the production expectation.

**Likely files**

- `README.md`
- `backend/README.md`
- `frontend/README.md`
- deployment docs / Compose docs

**Acceptance criteria**

- A new deployer can list the required devices, services, and subscriptions without reverse-engineering the repo.
- The docs distinguish mandatory production dependencies from optional upgrades.
- The docs state clearly that **public** production exposure still expects organizational hardening (monitoring, backups, key rotation) and **`P2`** quality gates such as CI — not only code features.
- The docs explain that iPhone/mobile-camera streaming is acceptable for testing, but not a production camera substitute.

**Progress**

- [x] Root `README.md` — deployment matrix, inventory, services, subscriptions, iPhone test path, **Current status** + **Deployer baseline checklist** updated for completed `P0` / `P1.1`–`P1.4` / `P1.3`.
- [x] `backend/README.md` / `frontend/README.md` — production-oriented notes (secrets, MapTiler, build-time env).

## P2 — quality, CI, and measured experiments

### `P2.1` Add CI

**Goal**

Run the high-value checks automatically.

**Required implementation**

- Add GitHub Actions for:
  - backend and detector test execution
  - frontend `npm run lint`
  - frontend `npm run build`
- Keep the CI fast enough for frequent PR use.
- Add a lightweight smoke path only if it is deterministic and does not require model downloads.

**Acceptance criteria**

- Pull requests fail on broken tests, broken frontend builds, or lint errors.
- CI does not depend on a physical camera or GPU.

**Progress**

- [x] `.github/workflows/ci.yml` — Ubuntu matrix: `pytest` (backend + detector tests with `detector/requirements-ci.txt`, no torch/YOLO install) and frontend `npm ci` + `lint` + `build` (dummy `VITE_*` for build).
- [x] `detector/requirements-ci.txt` — minimal OpenCV/NumPy for calibration tests; full `detector/requirements.txt` unchanged for real runs.
- [x] `backend/requirements.txt` — explicit `pytest-anyio` for async-marked tests on clean installs.
- [x] Frontend: `@types/node` + Vite 7–compatible alternate-`node_modules` plugin; ESLint fixes so `lint` passes in CI.

### `P2.2` Fine-tune YOLO11 before considering model swaps

**Goal**

Improve detector quality without paying the integration cost of a new detector family prematurely.

**Required implementation**

- Establish a parking-lot benchmark set, preferably from PKLot or a similar dataset.
- Measure the current YOLO11 baseline first.
- Fine-tune YOLO11 on parking data and compare accuracy and latency against the baseline.
- Only open a YOLO12 / RF-DETR evaluation if the fine-tuned YOLO11 result still misses agreed quality targets.

**Acceptance criteria**

- The experiment produces a small report with baseline vs tuned metrics.
- Any proposal to switch detector families includes measured justification, not model hype.

**Progress**

- [x] `detector/benchmark.py` measures YOLO11 latency/FPS, status counts, and optional labeled occupied-vs-not-occupied precision/recall/accuracy.
- [x] `detector/fine_tune_yolo11.py` provides a repeatable Ultralytics YOLO11 fine-tuning command.
- [x] `detector/parking_dataset.example.yaml` and `detector/benchmark_report.example.json` document dataset/report shapes for PKLot or pilot-camera workflows.
- [x] `detector/README.md` documents the baseline -> fine-tune -> tuned benchmark comparison flow.
- [x] Tests cover benchmark metric helpers and JSONL label loading.

### `P2.3` Improve non-production dwell demos

**Goal**

Make dwell-time features easier to demonstrate without polluting production behavior.

**Required implementation**

- Add a dev-only way to seed completed occupied-to-available history.
- Keep it disabled in real deployments.
- Ensure the simulator and dwell logic can coexist in development when explicitly requested.

**Acceptance criteria**

- A fresh dev setup can demonstrate the yellow "soon" signal without waiting for real parking-history accumulation.

**Progress**

- [x] `db.append_spot_history_row` + `db.seed_dwell_demo_sparse` — synthetic **past** completed sessions (chronologically before startup rows) for configurable spot IDs; idempotent when dwell count already meets target.
- [x] `PARKINGSPOTTER_SEED_DWELL_DEMO` — opt-in startup hook in `lifespan` after demo DB seed; uses `max(DWELL_MIN_COUNT, 3)` as target session count for spots `A1`, `B2`, `C1`.
- [x] `PARKINGSPOTTER_DWELL_CHECK_WITH_SIMULATOR` — run `dwell_checker_loop` alongside `simulator_loop` when the random simulator stays enabled.
- [x] Tests: `backend/tests/test_seed_dwell_demo.py`; `docker-compose.yml` + docs (`README.md`, `backend/README.md`) warn against production use.

## P3 — conditional infrastructure and R&D

### `P3.1` Message bus only when justified

- Revisit MQTT or NATS only after real multi-camera fan-in, burst rate, or offline delivery requirements are measured.
- Do not treat broker adoption as a prerequisite for Phase 5.

### `P3.2` Event-triggered VLM features

- Limit Gemma / VLM work to secondary workflows such as operator summaries, incident review, or privacy-related assistive flows.
- Do not put a VLM in the per-frame occupancy loop.

### `P3.3` Optional product-layer work

- Add observability, operator tooling, and dashboard features only after the core system is secure, tested, and multi-camera capable.

**Progress**

- [x] `GET /analytics/summary` returns status counts, available ratio, dwell readiness, and per-spot dwell stats for pilot dashboards.
- [x] `GET /cameras` reports camera last-observed time, stale/online state, and observed spot counts.
- [x] `GET /spots.csv` exports canonical spot state for spreadsheet/dashboard integrations.
- [x] Backend/root docs describe the pilot endpoints and privacy posture.

### `P3.4` Synthetic 3D street simulation and live visual overlay

**Goal**

Make the project more visually compelling for demos and development by adding a synthetic street scene with vehicles and pedestrians, while preserving the existing detector -> backend -> frontend architecture.

**Winning direction**

- Keep the map as the canonical operational view.
- Add the 3D scene as a separate visual layer and synthetic camera producer, not as a rewrite of the frontend or detector.
- Prefer a browser-native path first: `React + Three.js` for the initial implementation.
- Treat Unity / Unreal / CARLA as optional later upgrades if realism requirements exceed what Three.js can deliver.

**Required implementation**

1. Frontend visual simulation
   - Add an optional simulation view that renders a street / curbside parking scene with moving cars and pedestrians.
   - Support basic scripted events such as cruise, park, idle, door-open, enter, exit, depart, and pedestrian crossing.
   - Add YOLO-style bounding-box overlays for cars and people in the simulation view for visual support during demos.

2. Synthetic event integration
   - Drive spot-state updates from deterministic simulation events in development mode.
   - Keep the current backend and WebSocket contracts stable unless a later roadmap item explicitly changes them.

3. Synthetic camera stream path
   - Design the simulation so its camera output can later be consumed as a real detector input.
   - Prefer a bridge such as MediaMTX or an equivalent local media relay so the detector can subscribe through a normal video/stream interface.
   - Keep the detector compatible with swapping from synthetic stream to physical camera stream without frontend rewrites.

4. Modes and guardrails
   - Keep the feature optional and dev/demo-oriented until the core roadmap is complete.
   - Ensure the synthetic overlay path does not become the source of truth for occupancy in production.
   - Document how to run the simulation-only demo, and how to switch later to detector-on-synthetic-stream mode.

**Likely files / areas**

- `frontend/src/` new simulation components and route/view toggles
- optional new `simulation/` workspace or frontend-local simulation module
- backend simulator integration docs
- detector stream-ingest docs
- `README.md`

**Acceptance criteria**

- A contributor can run a visually rich local demo that shows cars and pedestrians moving through a simulated street scene.
- The demo can show YOLO-style rectangles around cars and people in real time.
- The architecture preserves a clean path from synthetic stream now to real camera stream later.
- The existing map flow remains intact and usable without the 3D simulation enabled.

**Progress**

- [x] `frontend/src/components/SimulationView.tsx` renders a Three.js synthetic street scene with scripted moving car, parked car, pedestrian crossing, and YOLO-style overlay boxes.
- [x] `frontend/src/App.tsx` adds a toolbar toggle between the canonical map and synthetic demo while leaving map behavior intact.
- [x] `frontend/README.md` and root `README.md` document that the 3D view is demo-only and backend/WebSocket spot state remains the source of truth.

## July 2026 roadmap — R0–R3 readiness push

Derived from `docs/PROJECT-REVIEW-2026-07.md`. Readiness target: **one real
camera, running continuously for 2+ weeks, with measured spot-state accuracy
against labeled ground truth, and an ops runbook.** Execute `R0` before `R1`,
`R1` before `R2`. Recommended agent tier per item is in
`docs/MODEL-ROUTING.md`.

## R0 — ship in-flight work safely

### `R0.1` Secure the projects API

**Goal**

Close the unauthenticated, uncapped write surface (project create/patch, asset upload, ZIP import) before the projects branch reaches any shared environment.

**Likely files**

- `backend/app/main.py`
- `backend/app/project_store.py`
- `backend/tests/test_projects_api.py`
- `frontend/src/lib/api.ts`
- `frontend/src/components/HybridStreetMapView.tsx`
- `README.md`, `backend/README.md`

**Required implementation**

- Add an operator token: when `PARKINGSPOTTER_PROJECTS_TOKEN` is set, all project **write** endpoints (`POST /projects`, `PATCH /projects/{id}`, `POST /projects/{id}/assets`, `POST /projects/import`) require `Authorization: Bearer <token>`; reject otherwise with `401`. When unset, writes stay open for local dev but log a startup warning.
- Frontend sends the token from `VITE_PROJECTS_TOKEN` when configured.
- Enforce upload size caps during streaming write (reject with `413`): `PARKINGSPOTTER_MAX_UPLOAD_MB` (default 512) for asset uploads.
- Enforce ZIP import limits: max entry count (default 2000), max total **uncompressed** size (default 1024 MB), reject nested unsafe paths (already handled — keep tests).
- Keep the existing extension allowlist and path-traversal guards; do not weaken.

**Acceptance criteria**

- With a token configured, unauthenticated writes are rejected; reads remain open.
- Oversized upload and oversized/over-dense ZIP are rejected with `413` and leave no partial project directory behind.
- Local dev without a token still works, with a logged warning.
- Tests cover: authorized write, unauthorized write, oversized upload, ZIP entry-count and uncompressed-size limits.

**Progress**

- [ ] Bearer-token gate on project write endpoints
- [ ] Streaming upload size cap
- [ ] ZIP import limits (entries, uncompressed size)
- [ ] Frontend token wiring
- [ ] Tests + docs

### `R0.2` SQLite durability and history retention

**Goal**

Prevent `database is locked` incidents under pilot load and stop unbounded `spot_history` growth.

**Likely files**

- `backend/app/db.py`
- `backend/app/main.py` (retention loop wiring)
- new backend tests

**Required implementation**

- Introduce a single connection helper in `db.py` that every operation uses; it applies `PRAGMA journal_mode=WAL` (once per database) and `PRAGMA busy_timeout=5000` (per connection).
- Add age-based history retention: delete `spot_history` rows older than `PARKINGSPOTTER_HISTORY_RETENTION_DAYS` (default 90), via a periodic background task (daily) plus one pass at startup.
- Retention must never delete rows belonging to a spot's **current open session** (an `occupied`/`soon` run without a closing `available`), regardless of age.

**Acceptance criteria**

- All db operations go through the shared helper; WAL and busy_timeout verified in a test.
- Pruning removes old completed-session rows, preserves open sessions, and dwell stats within the retention window are unchanged.
- Retention default and env var documented.

**Progress**

- [ ] Shared connection helper with WAL + busy_timeout
- [ ] Retention task + startup pass
- [ ] Open-session preservation rule
- [ ] Tests + docs

### `R0.3` "Soon" lifecycle correctness

**Goal**

Make the yellow signal trustworthy: dwell promotions must demote when the prediction misses, and the dwell checker must not race the multi-camera merge for canonical state.

**Likely files**

- `backend/app/main.py` (`dwell_checker_loop`)
- `backend/app/store.py`
- new backend tests

**Required implementation**

- Track dwell promotions explicitly in `SpotStore` (e.g., `spot_id -> promoted_at`) instead of writing bare canonical status, so promotion state survives merges.
- Composition rule (deterministic): merge computes the base canonical from observations as today; if base status is `occupied` and an active dwell promotion exists, the published status is `soon`. Detector-reported `soon` (motion) always passes through unchanged.
- Demotion: clear the promotion and republish `occupied` when elapsed ≥ `SOON_DEMOTE_FACTOR` (default 1.3) × mean dwell, or when the observation transitions to `available` (promotion cleared silently — normal flow).
- Broadcast on every published-status change, as today.

**Acceptance criteria**

- Sequence `occupied -> [dwell promotion] soon -> car stays past demote factor -> occupied` is covered by a test.
- A new observation for the same spot no longer silently reverts an active dwell promotion.
- Detector motion-`soon` is unaffected by promotion bookkeeping.
- `SOON_DEMOTE_FACTOR` documented alongside `SOON_THRESHOLD`.

**Progress**

- [ ] Promotion tracking in `SpotStore`
- [ ] Merge/promotion composition rule
- [ ] Demotion rule + env var
- [ ] Tests + docs

## R1 — contact with reality

### `R1.1` Occupancy metric v2 — polygon coverage

**Goal**

Replace axis-aligned slot-bbox IoU with slot-polygon coverage so angled/perspective street parking stops producing adjacent-slot false positives. This is the highest-leverage accuracy fix in the repo and must land **before** fine-tuning work.

**Likely files**

- `detector/detector/inference.py`
- `detector/detector/main.py` (CLI flag)
- `detector/benchmark.py` (same metric for benchmarking)
- `detector/tests/test_inference.py`
- `detector/README.md`, root `README.md`

**Required implementation**

- Occupancy signal per slot: coverage ratio = `area(vehicle_bbox ∩ slot_polygon) / area(slot_polygon)` (OpenCV `intersectConvexConvex` or equivalent polygon clipping; no new heavy dependency).
- Secondary confirmation signal: vehicle bbox bottom-center point-in-polygon (wire up the currently dead `_point_in_polygon`, or delete it if the coverage ratio alone wins in tests).
- New CLI flag `--occupancy-threshold` (default to be tuned, start 0.5); keep `--iou` as a deprecated alias with a warning for one release.
- Publish real detection confidence in plain mode instead of hardcoded `1.0`.
- Apply the identical metric in `benchmark.py` so before/after comparisons are valid.

**Acceptance criteria**

- Synthetic-geometry unit tests: angled slot with adjacent-lane vehicle no longer reports occupied (regression test for the bbox false positive); large vehicle fully covering a small slot reports occupied (regression for the low-IoU miss).
- ByteTrack/tracking mode uses the same occupancy signal.
- Benchmark run on an existing labeled clip documents before/after precision/recall in a short report committed under `docs/`.
- Deprecated `--iou` alias warns but works.

**Progress**

- [ ] Coverage-ratio implementation (plain + tracked paths)
- [ ] Point-in-polygon secondary signal wired or removed
- [ ] CLI flag + deprecation
- [ ] Real confidence in plain mode
- [ ] Benchmark parity + before/after report
- [ ] Tests + docs

### `R1.2` Real-camera pilot with labeled ground truth

**Goal**

Produce the project's first honest accuracy number: a fixed camera observed continuously, with labeled footage benchmarked through the real detector path.

**Required implementation**

- Choose the pilot scene (the `Description/1st Ave` assets suggest the intended street) and mount a fixed camera or RTSP-publishing phone rig per the README testing guidance.
- Record representative clips (varying light/traffic); label occupied/available ground truth per slot in the existing benchmark JSONL format.
- Author slots + homography calibration for the scene (`draw_slots.py --calibration`).
- Run `detector/benchmark.py` with the `R1.1` metric; record baseline results.
- Run the full stack (headless detector → backend → frontend) continuously for 2+ weeks; keep an ops log (crashes, disk, camera drops) and let dwell history accumulate.
- Write `docs/PILOT-REPORT.md`: setup, accuracy numbers, dwell-signal observations, incidents, and go/no-go conclusions for `R2` experiments.

**Acceptance criteria**

- Labeled dataset + calibration + slots config committed (or stored per privacy policy with paths documented).
- Benchmark report with per-slot accuracy, precision/recall for occupied.
- 2+ weeks continuous operation demonstrated, incidents logged.
- The yellow "soon" signal evaluated against reality at least anecdotally (did promoted spots actually free up?).

**Progress**

- [ ] Scene + camera rig
- [ ] Labeled clips + calibration
- [ ] Baseline benchmark report
- [ ] 2-week continuous run + ops log
- [ ] `docs/PILOT-REPORT.md`

### `R1.3` Single geometry implementation

**Goal**

Remove the divergent TypeScript re-implementations of geometry math (inverse-distance-weighted pixel→lat/lng, duplicated IoU) so calibration behavior is identical everywhere.

**Likely files**

- `detector/detector/server.py` (new endpoint)
- `detector/detector/street_calibration.py` / `detector/calibration.py`
- `frontend/src/components/HybridStreetMapView.tsx`
- `frontend/src/lib/api.ts`
- detector tests

**Required implementation**

- Add a detector-server endpoint (e.g., `POST /calibration/project`) that takes a street calibration JSON plus pixel points and returns lat/lng via the existing Python homography.
- Frontend calls this endpoint for pin sync; delete `mapPointFromPixel` (IDW) and the TS IoU copy, or reduce TS to display-only math (overlay scaling stays client-side).
- Graceful degradation: when the detector server is offline, pin sync is disabled with a clear UI state (no silent fallback to approximate math).

**Acceptance criteria**

- No coordinate-transform math remains in TypeScript.
- Pin positions from the hybrid view match `draw_slots.py --calibration` output for the same inputs (round-trip test on the server endpoint).
- Offline detector server produces an explicit UI state, not wrong pins.

**Progress**

- [ ] Server projection endpoint + tests
- [ ] Frontend consumes endpoint; TS IDW/IoU removed
- [ ] Offline handling
- [ ] Docs

## R2 — measured improvement (blocked on `R1.2` data unless noted)

### `R2.1` Fine-tuned YOLO11 vs per-slot patch classifier — head-to-head

- Fine-tune YOLO11n on PKLot + pilot frames (workflow exists: `detector/fine_tune_yolo11.py`).
- Implement a minimal per-slot patch classifier (CNRPark/mAlexNet style: crop slot polygon, classify occupied/empty) as a benchmark-only alternative.
- Compare on the `R1.2` labeled set: accuracy, latency, CPU load. Decision by numbers; the winner becomes the occupancy engine, the loser is documented and dropped.
- Note: YOLO remains required for the motion/"soon" path regardless of the occupancy winner.

### `R2.2` Time-bucketed dwell statistics

- Replace the global per-spot mean with time-of-day (and optionally weekday/weekend) bucketed medians/quantiles once pilot history exists.
- Keep the interface of `query_dwell_db` stable for callers; safe fallback to global stats when a bucket is sparse.
- No ML models here; escalate to survival models only if bucketed quantiles measurably underperform.

### `R2.3` Decompose `HybridStreetMapView.tsx`

- 807 lines and growing; split into focused modules (project management, media pane, detection overlay, calibration/pin sync, split-pane state) with a frontier-written decomposition plan executed by a mid-tier agent (`docs/MODEL-ROUTING.md`).
- Pure refactor: no behavior change; lint/build gate must stay green.

## R3 — product layer (deferred until R1 metrics exist)

- Multi-lot / zone data model (today: one implicit lot with hardcoded demo seeds).
- Operator dashboard (utilization, camera health, dwell readiness — API endpoints already exist).
- PWA polish for the driver-facing map.
- Observability: `/metrics`, structured logging, alerting.
- Repo hygiene: move review assets (`Project Review/`, `Gemma 4 capabilities`, PSDs) into `docs/` or an archive branch; drop committed YOLO weights (auto-downloaded).

## Done means done

A roadmap item is complete only when:

- implementation is merged
- tests cover the new behavior when practical
- relevant docs are updated
- the change follows the guardrails at the top of this file
