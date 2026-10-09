# Roadmap

Phases are small on purpose: each one is a single branch, a single spec
directory under `specs/`, and one PR that passes the verification gate.
Order follows the October 2026 review: ship R0 safely, film footage in
parallel, then get the first real accuracy number.

The detailed acceptance criteria for each `R` item live in `todo.md`. A phase's
spec directory turns that section into `requirements.md`, `plan.md` and
`validation.md`; tick the boxes here and in `todo.md` in the same PR.

History: April 2026 items `P0.1`–`P3.4` are complete (see `todo.md`).

---

## Phase 1: Secure the projects API (`R0.1`) + OpenCV pin

**Goal:** Close the unauthenticated, uncapped project write surface before it
reaches any shared environment, and stop OpenCV 5 from slipping in silently.

Spec: [`2026-10-09-secure-projects-api/`](2026-10-09-secure-projects-api/requirements.md)

- [x] Pin `opencv-python<5` (done in PR #1)
- [x] Bearer-token gate on project write endpoints
- [x] Streaming upload size cap
- [x] ZIP import limits (entries, uncompressed size)
- [x] Frontend token wiring
- [x] Tests + docs

---

## Phase 2: SQLite durability and history retention (`R0.2`)

**Goal:** No `database is locked` under pilot load; `spot_history` stops
growing without bound.

Spec: [`2026-10-09-sqlite-wal-retention/`](2026-10-09-sqlite-wal-retention/requirements.md)

- [x] Shared connection helper with WAL + busy_timeout
- [x] Retention task + startup pass
- [x] Open-session preservation rule
- [x] Tests + docs

---

## Phase 3: "Soon" lifecycle correctness (`R0.3`)

**Goal:** Yellow pins demote when the dwell prediction misses, and the dwell
checker no longer races the multi-camera merge.

- [ ] Promotion tracking in `SpotStore`
- [ ] Merge/promotion composition rule
- [ ] Demotion rule + env var
- [ ] Tests + docs

---

## Phase 4: Labeled footage and baseline benchmark (`R1.2`, part 1)

**Goal:** The project's first honest accuracy number, measured with today's
metric. Can run in parallel with Phases 1–3 (different files).

- [ ] Record tripod clips (2–3 lighting conditions)
- [ ] Frame extraction (~1 fps) for `benchmark.py --frames-dir`
- [ ] Labeling helper (show frame, key per slot, write benchmark JSONL)
- [ ] Label 200–500 frames; author slots + calibration for the scene
- [ ] Baseline benchmark report under `docs/`

---

## Phase 5: Occupancy metric v2, polygon coverage (`R1.1`)

**Goal:** Replace slot-bbox IoU with slot-polygon coverage so angled street
parking stops producing adjacent-slot false positives.

- [ ] Coverage-ratio implementation (plain + tracked paths)
- [ ] Point-in-polygon secondary signal wired or removed
- [ ] CLI flag + deprecation
- [ ] Real confidence in plain mode
- [ ] Benchmark parity + before/after report (same labels as Phase 4)
- [ ] Tests + docs

---

## Phase 6: Pilot soak test (`R1.2`, part 2)

**Goal:** Two weeks of continuous headless operation on a fixed camera, with
an ops log and a written pilot report.

- [ ] Fixed RTSP rig (phone on tripod with power, or cheap IP camera)
- [ ] 2-week continuous run + ops log
- [ ] "Soon" signal checked against reality
- [ ] `docs/PILOT-REPORT.md` with go/no-go for R2

---

## Phase 7: Single geometry implementation (`R1.3`)

**Goal:** Pixel→lat/lng and overlap math exist only in Python; the frontend
calls the detector server for pin sync.

- [ ] Server projection endpoint + tests
- [ ] Frontend consumes endpoint; TS IDW/IoU removed
- [ ] Offline handling
- [ ] Docs

---

## Later (blocked on Phase 6 metrics unless noted)

Replan this section once `docs/PILOT-REPORT.md` exists.

- `R2.1` Fine-tuned YOLO11 vs per-slot patch classifier head-to-head (the
  OpenCV 5 DNN/ONNX runtime experiment fits here)
- `R2.2` Time-bucketed dwell statistics
- `R2.3` Decompose `HybridStreetMapView.tsx` (not blocked; pure refactor)
- `R3` Product layer: multi-lot, operator dashboard, PWA, observability, repo hygiene
