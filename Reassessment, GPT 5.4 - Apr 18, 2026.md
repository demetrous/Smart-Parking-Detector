# ParkingSpotter — Project Reassessment (Apr 18, 2026)

This note reassesses the **product idea**, **tech stack**, **repo progress**, and **prior reassessment** (`Reassessment, Opus 4.7 - Apr 16, 2026.md`). It is grounded in the current tree: [README.md](README.md), [todo.md](todo.md), `backend/`, `detector/`, `frontend/`, [docker-compose.yml](docker-compose.yml), and the [Gemma 4 capabilities/](Gemma%204%20capabilities/) folder.

**Short version:** The architecture and scope are still the right shape for an MVP. The stack is modern and coherent. This is **not** a rewrite project — it is a **correctness, security, testing, and packaging** project, plus Phase 5 multi-camera design. One conclusion in the Apr 16 reassessment should be **retracted** (`react-map-gl`). Gemma 4 is **fair** to consider only as an **optional adjunct** (UX / semantics / R&D), not as the core occupancy engine.

---

## 1. Project idea — still sound in 2026

**What you are building:** Real-time per-slot parking state from a fixed camera, surfaced on a live map, with a differentiated **“soon”** signal.

**Why it still works:**

- **Occupancy via geometry** (detector polygons + IoU + debounce) is the standard, robust pattern for calibrated cameras.
- **Dual “soon” paths** — dwell-time from history and motion from ByteTrack — are a credible product differentiator; most hobby demos stop at free/occupied.
- **Three-service split** (detector → API → map) matches how you will deploy and scale later (separate processes, possibly separate machines).

**Product / research gaps** (unchanged from the prior reassessment and still valid):

- **Cold start for dwell:** Meaningful dwell stats need history; new deployments need priors, defaults, or a longer “learning” period in the UX.
- **Operator surface:** No dashboard for utilization, incidents, or calibration health — fine for MVP, limiting for “product.”
- **Trust / abuse:** Public or wide-area deployments need authenticated ingest and possibly rate limits (see §3).

---

## 2. Tech stack — mostly optimal for this stage

| Layer | Choice | Verdict |
|-------|--------|--------|
| Detector | Python, OpenCV, Ultralytics YOLO11, optional ByteTrack | **Keep.** Fits real-time bbox + tracking; export path to ONNX/TensorRT remains available when you need edge. |
| Backend | FastAPI, Pydantic, WebSockets, aiosqlite | **Keep** for single-instance MVP. Simple mental model, good DX. |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, MapLibre + MapTiler | **Keep.** Aligns with [README.md](README.md) and [frontend/README.md](frontend/README.md). |
| Map bindings | `react-map-gl` v8 (`react-map-gl/maplibre`) | **Keep** — see §5.1 (correction vs Opus). |
| Persistence | SQLite + history table | **Keep** until multi-tenant or HA requirements appear; then reassess Postgres + migrations. |

**When to deviate (later, not now by default):**

- **Message bus (MQTT/NATS):** Reasonable when many cameras or high publish rates; premature if you have one detector and modest update frequency. Revisit as part of Phase 5, not as a universal P1.
- **YOLO → RF-DETR / newer YOLO / fine-tune:** Treat as **measured** experiments on **your** footage (PKLot, CNRPark+EXT, or your own). Biggest ROI is often **fine-tuning YOLO11** before swapping families.
- **Migrations:** Add when schema churn increases (homography blobs, per-camera config). Alembic or lightweight SQL migration scripts are both fine.

---

## 3. Codebase & progress — what is actually there

### 3.1 Implemented end-to-end (Phases 1–4)

Evidence in repo:

- **Backend:** REST + WebSocket hub, in-memory store with SQLite write-through ([backend/app/main.py](backend/app/main.py), [backend/app/store.py](backend/app/store.py), [backend/app/hub.py](backend/app/hub.py), [backend/app/db.py](backend/app/db.py)).
- **Dwell checker vs simulator:** Mutually exclusive via `SIMULATOR` env ([backend/app/main.py](backend/app/main.py)) — matches [README.md](README.md) and [todo.md](todo.md).
- **Detector:** CLI, slots config, IoU occupancy, debounce, optional `--track` motion path ([detector/detector/](detector/detector/)).
- **Frontend:** Map, markers, theme, WS reconnect pattern ([frontend/src/](frontend/src/)).

**Conclusion:** Phases 1–4 as described in [README.md](README.md) roadmap are **substantially reflected in code**, not just aspirational.

### 3.2 Partial / skeleton

- **Docker:** [docker-compose.yml](docker-compose.yml) declares `build:` with `Dockerfile` per service, but **no Dockerfiles exist** in the workspace. Compose is a **skeleton**, not a runnable stack today.
- **Phase 5:** [todo.md](todo.md) lists homography, merge rules, `GET /spots?camera=`. Example config includes `camera_id` at file level ([detector/slots.example.json](detector/slots.example.json)); full multi-camera/homography workflow is **not** complete.

### 3.3 Gaps and bugs worth fixing early

**a. Unauthenticated `POST /spots`**

```179:186:backend/app/main.py
    @app.post("/spots")
    async def upsert_spot(spot: Spot) -> dict:
        """Detector pushes updates here; backend persists and broadcasts."""
        await store.upsert(spot)
        await hub.broadcast(
            Event(type="spot.update", payload=spot.model_dump(mode="json"))
        )
        return {"ok": True}
```

Anyone who can reach the backend can spoof occupancy. For any non-localhost deployment, add at least a **shared secret / HMAC** or **mTLS** between detector and API.

**b. Dwell-time inconsistency: `occupied_since_db` vs `query_dwell_db`**

`query_dwell_db` treats both `occupied` and `soon` as starting a dwell segment; `occupied_since_db` only looks for `occupied`:

```104:125:backend/app/db.py
    for status, recorded_at in rows:
        if status in ("occupied", "soon") and occupied_start is None:
            occupied_start = datetime.fromisoformat(recorded_at)
        ...
async def occupied_since_db(spot_id: str) -> datetime | None:
    ...
            "WHERE spot_id = ? AND status = 'occupied' "
```

If motion promotes a spot to `soon` before the backend’s dwell logic runs, elapsed time for dwell-based “soon” can be **wrong**. **Fix:** align `occupied_since_db` with the same state machine as `query_dwell_db` (e.g. most recent transition into `occupied` **or** `soon` as “session start,” with clear rules for double-yellow edge cases).

**c. SQLite upsert omits `lat` / `lng` on conflict**

On conflict, only `status`, `confidence`, `camera_id`, `updated_at` are updated — not coordinates:

```49:53:backend/app/db.py
            ON CONFLICT(id) DO UPDATE SET
                status      = excluded.status,
                confidence  = excluded.confidence,
                camera_id   = excluded.camera_id,
                updated_at  = excluded.updated_at
```

If slot geometry or manual lat/lng changes, persisted rows can **drift** from what the detector POSTs until DB is rebuilt. Low frequency, but worth fixing before Phase 5 calibration churn.

**d. Detector env vs config**

Compose sets `BACKEND_URL` for the detector service; the detector reads `backend_url` from JSON config ([todo.md](todo.md) / typical `slots.json`). Ensure **one** source of truth or document the override — avoids “works in compose, empty URL in practice” confusion.

**e. Documentation nit**

[README.md](README.md) detector example has a typo: `sample.mp4--preview` should be `sample.mp4 --preview`.

**f. No automated tests, no CI**

No `pytest` / `vitest` harness found; no `.github/workflows`. For a system with debounce, IoU, dwell stats, and WS clients, tests are the highest-leverage safety net before refactors.

---

## 4. Gemma 4 capabilities folder — fair assessment

**What the folder is:** A set of **screenshots** (social / demo style) under [Gemma 4 capabilities/](Gemma%204%20capabilities/), not Google’s official spec sheet, license text, or reproducible benchmarks for *your* hardware and video.

**What it suggests (directionally):**

- Multimodal / local-first narratives (browser WebGPU, phone NPU, desktop `llama.cpp`, etc.).
- A recurring **pattern**: **fast detector + VLM for language/summary** — not “VLM replaces detector.”

**Fair conclusion for ParkingSpotter:**

| Role | Gemma 4 (or any VLM) |
|------|----------------------|
| Per-frame occupancy, IoU, debounce | **Poor primary fit** — keep YOLO/RF-DETR-style detectors. |
| Motion “soon” via centroids | **Poor substitute** for ByteTrack-style geometry. |
| NL summaries, operator Q&A, incident captions | **Good optional fit** if gated (low rate, aggregated state). |
| Privacy masking / scene QA on stored frames | **Possible R&D** — validate latency, false positives, and policy. |

**Recommendation:** Do **not** plan Gemma 4 as the backbone of real-time slot state. If you experiment, treat it as **event-triggered** (e.g. spot already occupied + threshold crossed) and measure latency and stability on your cameras.

---

## 5. Revisiting Opus 4.7 (Apr 16, 2026) conclusions

### 5.1 Should be corrected- **`react-map-gl` “dead weight”:** **Incorrect.** The app imports MapLibre bindings from `react-map-gl/maplibre` in [frontend/src/components/ParkingMap.tsx](frontend/src/components/ParkingMap.tsx) and [frontend/src/components/MapMarkers.tsx](frontend/src/components/MapMarkers.tsx). At most, argue **bundle size** or API preference — not unused dependency.

### 5.2 Still strong

- **Architecture** (detector / FastAPI / WS / React): **Strong.**
- **`POST /spots` auth gap:** **Strong** (still open in code).
- **Dwell `occupied_since_db` mismatch:** **Strong** (confirmed in [backend/app/db.py](backend/app/db.py)).
- **No tests / no CI:** **Strong.**
- **Docker compose without Dockerfiles:** **Strong** ([docker-compose.yml](docker-compose.yml) vs missing `Dockerfile*`).
- **Simulator vs dwell mutual exclusion:** **Strong** — intentional; consider a **dev-only** “seed synthetic history” mode for demos (Opus suggestion remains valid).

### 5.3 Reasonable but not mandatory yet

- **MQTT/NATS before Phase 5:** Directionally fine for many cameras; **not** required for current single-detector MVP. Schedule when multi-camera traffic or fan-in justifies ops complexity.
- **YOLO12 / RF-DETR / fine-tune:** Engineering opinions — validate on your data before swapping.

### 5.4 Gemma 4 addendum in Opus

The **hybrid** mental model (detector + optional VLM) is **aligned** with the screenshot narrative. Specific throughput numbers and device claims should be treated as **unverified** unless cross-checked against official docs and your own runs — the Apr 16 file already caveats this; keep that caveat.

---

## 6. Recommended roadmap (refined)

| Priority | Task | Rationale |
|----------|------|-----------|
| **P0** | Authenticate `POST /spots` (HMAC or similar) | Blocks trivial spoofing on any exposed deployment. |
| **P0** | Fix dwell `occupied_since_db` vs `query_dwell_db` alignment | Silent correctness bug for yellow-from-dwell. |
| **P0** | Minimal test suite: dwell parsing, upsert semantics, debounce/IoU units | Unlocks safe refactors. |
| **P1** | Add Dockerfiles + make compose truthful; healthchecks, volumes | Matches Phase 7 intent; improves onboarding. |
| **P1** | Phase 5: homography tool, merge rules, `GET /spots?camera=` | Core scale-out story for real lots. |
| **P1** | Fix SQLite upsert to update `lat`/`lng` (or document rebuild) | Avoids stale map pins after calibration changes. |
| **P2** | CI (lint, typecheck, smoke backend + synthetic detector clip) | Catches regressions. |
| **P2** | Model experiments: fine-tune YOLO11 on parking data; compare RF-DETR if needed | Data-driven accuracy. |
| **P2** | Optional: MQTT/NATS ingest when multi-detector load warrants it | Avoid premature infrastructure. |
| **P3** | Phase 6 synthetic stream | Great for regression; larger investment. |
| **P3** | Gemma 4 (or other VLM) prototype: NL popup / operator assist only | Keep off the hot path until proven. |

---

## 7. TL;DR

- **Idea:** Still good; “soon” remains the differentiator.
- **Stack:** Appropriate; **no wholesale replacement** recommended.
- **Codebase:** Phases 1–4 are **real** in the repo; Docker and Phase 5 are **not** done to the level the compose file implies.
- **Opus reassessment:** Mostly right; **drop** the `react-map-gl` dead-weight claim.
- **Gemma 4 folder:** Useful as **directional** input only; use VLMs **adjacent** to the detector, not instead of it.

Next concrete wins: **secure ingest**, **dwell fix**, **tests**, **Docker reality**, then **Phase 5**.

---

*Generated as part of an internal reassessment pass; not a substitute for production security review or formal model benchmarking.*
