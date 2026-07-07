# Independent Project Review — July 7, 2026

Reviewer: Claude (Fable 5), acting as independent principal engineer.
Scope: full read of docs (`README.md`, `todo.md`, April 2026 review corpus,
Opus 4.7 corrections), backend, detector, frontend, tests, CI, and the
uncommitted projects-feature branch. This document is the evidence base for
the `R0`–`R3` roadmap in `todo.md` and the routing rules in
[`MODEL-ROUTING.md`](MODEL-ROUTING.md).

> Line references are as of 2026-07-07 and will drift; anchor on function
> names when they do.

## Verdict

The idea is commercially sound, the architecture is right-sized, and the
April–June hardening (P0–P2) was executed with unusual discipline. The
project's core problem is not code quality — it is that **the system has never
been validated against a real camera**, while the demo/presentation layer
keeps growing. One pilot deployment separates this project from knowing
whether the product works. Secondary finding: the core occupancy math is the
weakest link and is cheaper to fix than any model upgrade.

## Product assessment

- Parking occupancy from fixed cameras is a proven commercial category
  (Cleverciti, Parquery, Genetec), which validates demand and implies the moat
  is **deployment economics and the data flywheel**, not the detector.
- The genuine differentiator is the **"soon"** signal (dwell prediction +
  motion). Every week without a real camera is a week the per-spot dwell
  dataset — the defensible asset — isn't accumulating.
- **Demo-to-core inversion:** `HybridStreetMapView.tsx` (~807 lines) +
  `SimulationView.tsx` (~573 lines) exceed the detection core
  (`inference.py` + `tracker.py`, ~450 lines). Hence the demo-freeze guardrail
  in `AGENTS.md`.

## Stack verdict

FastAPI + SQLite + WebSocket, React 19 + Vite + MapLibre, YOLO11n + ByteTrack,
HTTP ingest with HMAC, Compose + GitHub Actions: **all right-sized; no changes
recommended.** MQTT/NATS, Postgres, and detector-family swaps remain correctly
deferred pending measured need.

## Verified strengths (culture to preserve)

- The prescriptive `todo.md` spec format is the repo's most valuable process
  asset — it is why mid-tier implementation agents landed P0–P2 cleanly.
- The April cross-model verification pass caught real bugs; the major ones are
  confirmed fixed in code: background-task references (`backend/app/main.py`
  `_spawn_background`), wall-clock history timestamps + `spot_history` index
  (`backend/app/db.py`), negative-elapsed clamp in `dwell_checker_loop`.
- HMAC ingest auth is correctly implemented (constant-time compare, replay
  window, stale *and* future-dated rejected).
- ZIP import guards path traversal (`backend/app/project_store.py`).

## Findings (July 2026, beyond the April reviews)

Numbered; mapped to roadmap items in `todo.md`.

1. **Occupancy metric discards polygon data — highest-leverage fix in the repo.**
   `detector/detector/inference.py` `_bbox_from_polygon` collapses slot
   polygons to axis-aligned boxes; `_point_in_polygon` is dead code (defined,
   never called). On angled/perspective street parking, a car in an adjacent
   slot overlaps the neighbor's bbox → false "occupied". Symmetric IoU is also
   the wrong measure (a large vehicle covering a small slot yields *low* IoU).
   Fix: coverage ratio `area(vehicle_bbox ∩ slot_polygon) / area(slot_polygon)`
   + bottom-center point-in-polygon. → `R1.1`. Must precede fine-tuning,
   because it changes benchmark ground-truth semantics.

2. **"Soon" never demotes, and has no writer precedence.** `dwell_checker_loop`
   promotes occupied→soon at 70 % of mean dwell; if the car stays (right-skewed
   dwell distributions guarantee many do), the pin stays yellow indefinitely —
   training users that yellow means nothing. Separately, the dwell checker and
   the multi-camera merge layer both write canonical state with no defined
   precedence; the next observation-triggered merge silently reverts a dwell
   promotion. → `R0.3`.

3. **Projects API is an unauthenticated, uncapped write surface.**
   `POST /projects`, asset upload, and ZIP import accept anonymous writes with
   no size limits (disk exhaustion via one large upload or crafted ZIP), while
   `POST /spots` requires HMAC — an inconsistent security posture on the same
   service. Path traversal *is* handled. → `R0.1`, blocking merge of the
   in-flight branch to any shared environment.

4. **Single-process constraint is implicit.** In-memory `SpotStore` + `Hub`
   silently break with `uvicorn --workers 2` (split state, partial WS fan-out).
   Documented as guardrail #9 in `AGENTS.md`; consider a startup assertion.

5. **SQLite: no WAL, no busy_timeout, connection-per-operation, unbounded
   `spot_history`.** Lock contention ("database is locked") is the first ops
   incident waiting to happen once the dwell checker, multi-camera posts, and
   `/analytics/summary` (N+1 dwell queries per request) overlap. → `R0.2`.

6. **Geometry logic duplicated across languages, divergently.** IoU exists in
   Python and again in TS (`HybridStreetMapView.tsx`); pixel→lat/lng is proper
   homography in Python (`detector/calibration.py`) but inverse-distance
   weighting in TS — which distorts positions between anchors. One
   implementation, in Python, consumed over HTTP. → `R1.3`.

7. **Browser-driven detection must stay demo-only.** The hybrid view posting
   frames to `detector.server` is fine for authoring/demos; production is the
   headless RTSP detector. Encoded as guardrail #5 so future agents don't grow
   a parallel pipeline.

8. **Repo hygiene.** Committed model weights (`detector/yolo11n.pt` —
   ultralytics auto-downloads), phone screenshots/PSDs at repo root
   (`Project Review/`, `Gemma 4 capabilities`, `Description/`), and plain-mode
   detection publishing hardcoded `confidence = 1.0`
   (`detector/detector/inference.py` `_process_plain`) — fake certainty that
   will poison any future confidence-weighted merge. Cleanup + real
   confidences: fold into `R1.1`/`R2` work as touched.

## Readiness definition

"Ready" means: **one real camera, running continuously for 2+ weeks, with
measured spot-state accuracy against labeled ground truth, and an ops
runbook.** Nothing blocks this except the `R0`/`R1` items. The through-line
for all prioritization: *stop adding surfaces, start measuring the one that
exists.*

## Roadmap summary (specs live in `todo.md`)

- **R0** — ship in-flight work safely: secure projects API (`R0.1`), SQLite
  WAL + retention (`R0.2`), "soon" lifecycle correctness (`R0.3`).
- **R1** — contact with reality: occupancy metric v2 (`R1.1`), real-camera
  pilot + labeled benchmark (`R1.2`), single geometry implementation (`R1.3`).
- **R2** — measured improvement: fine-tune vs patch-classifier head-to-head
  (`R2.1`), time-bucketed dwell (`R2.2`), decompose `HybridStreetMapView`
  (`R2.3`).
- **R3** — product layer, deferred: multi-lot/zone model, operator dashboard,
  PWA, observability.
