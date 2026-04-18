# ParkingSpotter — Consensus Roadmap

This file is the execution roadmap distilled from the April 2026 intermediate review. It is intentionally prescriptive so future agents can work from it without re-litigating architecture.

## Global guardrails

- Keep the current three-service shape: `detector -> backend -> frontend`.
- Do not rewrite the stack or replace the core transport before the current MVP is hardened.
- Keep `react-map-gl/maplibre`; it is actively used in the frontend map components.
- Keep detector ingest on HTTP `POST /spots` through `P1`. Do not add MQTT/NATS unless measured multi-camera load justifies it later.
- Keep YOLO11 + ByteTrack as the baseline detector path. Fine-tune it on parking data before evaluating detector-family swaps.
- Treat Gemma / VLM ideas as optional, event-triggered adjunct features only. They must not sit on the per-frame occupancy hot path.
- Prefer additive, test-backed changes. Any schema or API change must update docs in the same task.

## Execution order

1. `P0.1` Secure detector ingest `Completed Apr 18, 2026`
2. `P0.2` Fix dwell-time session logic `Completed Apr 18, 2026`
3. `P0.3` Add minimal automated tests `Completed Apr 18, 2026`
4. `P1.1` Make Docker truthful `Completed Apr 18, 2026`
5. `P1.2` Fix SQLite coordinate upsert `Completed Apr 18, 2026`
6. `P1.3` Build Phase 5 multi-camera foundation `In progress — core ingest + API done; homography + draw_slots calibration pending`
7. `P1.4` Clean up detector configuration ownership `Completed Apr 18, 2026`
8. `P1.5` Define the production deployment baseline
9. `P2` items only after the above are complete

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
- [ ] Homography calibration artifact and pixel→lat/lng auto-fill (`P1.3` remainder).
- [ ] `draw_slots.py` optional calibration file consumption and coordinate auto-fill (`P1.3` remainder).

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
- The docs state clearly that the current codebase still requires `P0` and `P1` hardening work before public production exposure.
- The docs explain that iPhone/mobile-camera streaming is acceptable for testing, but not a production camera substitute.

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

### `P2.3` Improve non-production dwell demos

**Goal**

Make dwell-time features easier to demonstrate without polluting production behavior.

**Required implementation**

- Add a dev-only way to seed completed occupied-to-available history.
- Keep it disabled in real deployments.
- Ensure the simulator and dwell logic can coexist in development when explicitly requested.

**Acceptance criteria**

- A fresh dev setup can demonstrate the yellow "soon" signal without waiting for real parking-history accumulation.

## P3 — conditional infrastructure and R&D

### `P3.1` Message bus only when justified

- Revisit MQTT or NATS only after real multi-camera fan-in, burst rate, or offline delivery requirements are measured.
- Do not treat broker adoption as a prerequisite for Phase 5.

### `P3.2` Event-triggered VLM features

- Limit Gemma / VLM work to secondary workflows such as operator summaries, incident review, or privacy-related assistive flows.
- Do not put a VLM in the per-frame occupancy loop.

### `P3.3` Optional product-layer work

- Add observability, operator tooling, and dashboard features only after the core system is secure, tested, and multi-camera capable.

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

## Done means done

A roadmap item is complete only when:

- implementation is merged
- tests cover the new behavior when practical
- relevant docs are updated
- the change follows the guardrails at the top of this file
