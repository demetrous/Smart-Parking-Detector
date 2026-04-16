# ParkingSpotter — Project Reassessment (Apr 2026)

Here's my honest review after reading the README, todo, all three services, and the shared infra. Short version: **the architecture is genuinely solid and well-scoped for an MVP — this is the right shape of system.** What's missing is mostly production-hardening plus a handful of small tech-stack updates worth making before you tackle Phase 5.

---

## 1. Project idea — still sound in 2026

The problem (real-time parking availability from overhead cameras) is legitimately useful, and the 3-signal approach — hard IoU occupancy + dwell-time prediction + motion "soon" — is the right framing. I've seen multiple 2025-era commercial systems converge on essentially the same pattern, so you're on the right track.

A few framing tweaks worth considering:

- **"Soon" is the product differentiator.** Most OSS parking detectors stop at occupied/available. Your dual-signal "soon" is genuinely novel and should be marketed as such — consider surfacing a *confidence/ETA* on the popup (e.g., "likely free in ~90 s, 72% confidence") rather than just a colour.
- **The dataset assumption is fragile.** Dwell-time only works once you have ≥3 completed cycles per spot. For a brand-new deployment that's 3–30 days of cold start. Worth having an onboarding mode that uses regional/global priors (e.g., "street parking in downtown ≈ 45 min mean") until per-spot stats ripen.
- **Business model gap.** There's no user identity, no reservations, no analytics dashboard for lot operators. That's fine if this stays a demo, but the next obvious product surface (operator dashboard showing utilisation heatmaps, revenue-per-slot, peak hours) is missing from the roadmap entirely.

---

## 2. Tech stack — 80% great, 20% worth revisiting

### Keep as-is

| Layer | Choice | Verdict |
|---|---|---|
| Backend framework | FastAPI + Pydantic v2 | Still the right pick; async-native, WS-native. |
| Real-time transport | WebSocket hub | Correct for a single-instance MVP. |
| Map | MapLibre GL + MapTiler | Open, free tier, no lock-in — good. |
| Styling | Tailwind v4 | Current. |
| Build tool | Vite 7 | Current. |
| Tracking | ByteTrack via Ultralytics | Still the right default; near-zero dep cost. |

### Consider updating / replacing

**1. YOLO11n → YOLO12 or a parking-specific fine-tune.**
YOLO11 (Oct 2024) is fine, but Ultralytics released YOLO12 in early 2025 with attention-based improvements on small objects — which is exactly your problem (cars viewed from above, often occluded). Better still: take any YOLO variant and fine-tune it on **PKLot** or **CNRPark+EXT** directly; a 15-minute fine-tune typically adds 5–10 points of mAP on top-down parking footage vs. generic COCO weights.

**2. `react-map-gl` is dead weight.**
Your `package.json` lists both `maplibre-gl` and `react-map-gl@8`, but your actual code (from what I can see in `ParkingMap.tsx` / `MapMarkers.tsx`) appears to use MapLibre directly. Either adopt `react-map-gl` fully (it genuinely simplifies the imperative map API) or drop it from dependencies — right now it's bundle bloat.

**3. SQLite is fine, but Alembic-style migrations are not optional past Phase 5.**
Right now schema changes require you to delete `parking.db`. Once you add `camera_id` filtering, homography matrices, or anything user-facing, you'll need migrations. Cheap options: `alembic` (heavyweight but standard) or `yoyo-migrations` (simpler for SQLite).

**4. HTTP POST per event → MQTT or NATS for the detector.**
`POST /spots` is fine at 1 camera / 1 lot. At 10 cameras × 200 spots with 1-Hz updates you're wasting 2000 TCP handshakes/sec. A lightweight message bus (Mosquitto MQTT or NATS JetStream) would let the detector publish at wire speed and let the backend consume asynchronously. This directly unblocks Phase 5 (multi-camera) — swap it now, not later.

**5. Add an edge-inference path.**
The detector currently runs PyTorch on the host. For actual deployment on a Jetson / mini-PC you want ONNX Runtime or TensorRT. Ultralytics exports both with one line (`model.export(format="onnx")`). Not urgent but worth documenting as a deployment path.

**6. Docker compose file is slightly stale.**
`version: "3.9"` at the top has been a no-op since Docker Compose v2 (2023). Drop it. Also, there are no actual `Dockerfile`s in `backend/`, `frontend/`, or `detector/` — the compose file references builds that don't exist.

---

## 3. Gaps in the current code (things I'd fix before Phase 5)

**a. `POST /spots` is unauthenticated.** Anyone who can reach the backend can spoof spot state. Even an HMAC shared secret between detector and backend (header signature on the JSON body) would close this. Critical once you expose the backend to the internet.

**b. Dwell-time edge case in `db.py`.** In `query_dwell_db` at `backend/app/db.py:104-110`, the state machine counts the *first* transition into `occupied OR soon` as the dwell start. That's correct, but `occupied_since_db` at line 119-135 only looks for `status = 'occupied'`. If a spot goes `available → soon → occupied` (possible with motion-first logic), `occupied_since_db` picks the later timestamp, which underestimates elapsed time and makes the dwell checker too conservative. Fix: also accept `soon` as a valid "occupied-since" marker, consistent with the dwell query.

**c. `SpotsProvider.tsx` rebuilds `byId` Map on every render.**
`new Map(spots.map(...))` inside `useMemo` is fine, but you're also passing `byId` as part of context value — any consumer using it will re-render on every spot update, even for spots they don't care about. Either (1) don't expose `byId` and let consumers select by id, or (2) use Zustand / Jotai / `useSyncExternalStore` which have proper selector support. Not urgent, but it'll bite once you have 500+ pins.

**d. No tests at all.**
Zero `test_*.py`, zero `*.test.ts`. For a system with this many moving parts (debounce logic, IoU math, dwell statistics, WS reconnect) this is the highest-leverage thing you could add. Minimum viable: pytest for `_iou()`, `query_dwell_db()`, and the debounce state machine. Synthetic frames fixtures for the detector.

**e. No observability.**
No structured logging, no metrics endpoint, no `/metrics` Prometheus scrape. At MVP this is fine; at "running on a real camera in the wild" this is the first thing you'll miss when something goes wrong at 3 AM.

**f. The simulator and dwell checker never run together.**
In `backend/app/main.py:136-139` it's one-or-the-other. That's probably intentional, but it means you can't *test* dwell-time logic without waiting for real history to accumulate. A test-mode switch that runs the simulator *and* seeds synthetic history into `spot_history` would let you demo the yellow "soon" transition in 30 seconds instead of hours.

---

## 4. Revised roadmap (my suggestion)

Your current Phase 5 → 6 → 7 ordering is reasonable, but I'd reshuffle:

| Priority | Task | Rationale |
|---|---|---|
| **P0** | Add HMAC auth on `POST /spots` | Security hole; trivial to close |
| **P0** | Fix `occupied_since_db` dwell bug | Silent correctness issue |
| **P0** | Write pytest suite for IoU, debounce, dwell | You can't refactor safely without it |
| **P1** | Swap HTTP → MQTT/NATS for detector → backend | Prerequisite for multi-camera |
| **P1** | Phase 5 (multi-camera + homography) | Your roadmap priority |
| **P1** | Write the missing Dockerfiles | Compose file is a lie without them |
| **P2** | Operator dashboard (utilisation charts, heatmap) | First real "product" surface |
| **P2** | YOLO fine-tune on PKLot | Biggest accuracy win per hour invested |
| **P2** | Drop `react-map-gl` or commit to it | Clean up bundle |
| **P3** | Phase 6 synthetic stream (Three.js → MediaMTX → RTSP) | Test-infra investment |
| **P3** | Alembic migrations, `/metrics`, structured logs | Production-hardening bundle |
| **P3** | ONNX/TensorRT export docs | Edge-deployment path |

---

## 5. Things I specifically like

So this doesn't read as all criticism:

- The **separation of the raw IoU debounce from the published status** (`_debounced_occupied` in `detector/detector/inference.py:107`) is subtle and correct — it's exactly how you keep "soon" from resetting the "available" transition. Good design.
- The **WS reconnect with exponential backoff + `connected` state exposed to the UI** is well-executed and the kind of detail that separates demos from products.
- The **write-through store** (in-memory + SQLite) in `backend/app/store.py` is the right complexity level for this stage — no Redis, no read-replicas, just works.
- The `draw_slots.py` one-time calibration workflow is pragmatic. A lot of OSS projects in this space try to auto-discover slots (badly); yours picks the right "20 minutes of human config, forever of reliable output" trade-off.
- The `dev.ps1` Google Drive workaround is weirdly delightful. Annoying problem, clean solution.

---

## TL;DR

The **idea is good**, the **architecture is correct**, and the **code quality is above average for a personal project** — this isn't a rewrite situation, it's a "polish the rough edges and fill the production gaps" situation. The three biggest leverage points are (1) auth on `POST /spots`, (2) MQTT/NATS replacing HTTP-per-event before Phase 5, and (3) a real test suite. Everything else on the list is nice-to-have.

Happy to dive deeper into any of these — I can sketch the MQTT migration, the auth scheme, or the fine-tune workflow in more detail if you want. Just let me know which direction, and I'd recommend switching me to Agent mode when you want any of it actually implemented.