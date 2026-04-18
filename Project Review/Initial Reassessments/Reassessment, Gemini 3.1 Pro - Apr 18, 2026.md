# ParkingSpotter — Project Reassessment (Apr 18, 2026)

This reassessment covers the **product idea**, **tech stack**, **repo progress**, and **whole codebase** as implemented today. It references [README.md](README.md), [todo.md](todo.md), `backend/`, `detector/`, `frontend/`, [docker-compose.yml](docker-compose.yml), the prior notes [Reassessment, Opus 4.7 - Apr 16, 2026.md](Reassessment,%20Opus%204.7%20-%20Apr%2016,%202026.md) and [Reassessment, GPT 5.4 - Apr 18, 2026.md](Reassessment,%20GPT%205.4%20-%20Apr%2018,%202026.md), and the screenshot-only folder [Gemma 4 capabilities/](Gemma%204%20capabilities/).

**TL;DR:** The architecture and scope are the right shape for an MVP. The stack is coherent and current. This is **not** a rewrite—it is a **security, correctness, testing, packaging, and Phase 5 design** effort. Gemma 4 is fair to consider only as an **optional adjunct** (semantics / UX / R&D), not as the occupancy backbone. Opus’s `react-map-gl` “dead weight” claim should be **retracted**; GPT’s correction is **correct**.

---

## 1. Project idea — still sound

**What you are building:** Real-time per-slot parking state from (typically) a fixed camera, shown on a live map, with a differentiated **“soon”** signal.

**Why it works:**

- **Geometry-first occupancy** (slot polygons + IoU + debounce) is the standard robust pattern for calibrated views.
- **Two “soon” paths**—dwell-time from `spot_history` and motion from optional ByteTrack—are a credible differentiator; many demos stop at free/occupied.
- **Three-service split** (detector → API → map) matches how you will deploy and scale (separate processes or machines later).

**Product / research gaps** (still valid):

- **Cold start for dwell:** Useful stats need completed cycles; new deployments need priors, defaults, or honest UX (“learning”).
- **Operator surface:** No utilization dashboard or calibration health—fine for MVP, limiting as a product.
- **Trust:** Wide-area or internet-exposed backends need authenticated ingest and rate limits (see §3).

---

## 2. Tech stack — mostly optimal for this stage

| Layer | Choice | Verdict |
|-------|--------|--------|
| Detector | Python, OpenCV, Ultralytics YOLO11, optional ByteTrack | **Keep.** Fits bbox + tracking; ONNX/TensorRT export remains the edge path when you need it. |
| Backend | FastAPI, Pydantic, WebSockets, aiosqlite | **Keep** for single-instance MVP. |
| Frontend | React 19, TypeScript, Vite, Tailwind v4, MapLibre + MapTiler | **Keep.** Matches [README.md](README.md) and [frontend/README.md](frontend/README.md). |
| Map bindings | `react-map-gl` v8 (`react-map-gl/maplibre`) | **Keep** — used in [frontend/src/components/ParkingMap.tsx](frontend/src/components/ParkingMap.tsx) and [frontend/src/components/MapMarkers.tsx](frontend/src/components/MapMarkers.tsx). |
| Persistence | SQLite + history table | **Keep** until multi-tenant or HA; then reassess Postgres + migrations. |

**When to deviate later (not mandatory now):**

- **MQTT/NATS:** Justified when many cameras or high fan-in; premature for one detector and modest update rates—schedule with Phase 5 load.
- **Detector family / fine-tune:** Treat YOLO12, RF-DETR, or parking-dataset fine-tunes as **measured** experiments on **your** footage; often fine-tuning the current YOLO11 stack is the best first hour.
- **DB migrations:** Add when schema churn grows (homography blobs, per-camera config). Alembic or small SQL migration scripts both work.

**More optimal “up to date” framing:** The README already positions YOLO11 and modern React; the highest-ROI updates are **process** (tests, auth, Docker truth) and **data** (fine-tune on PKLot / your video), not a greenfield stack swap.

---

## 3. Codebase & progress — what is actually there

### 3.1 Implemented end-to-end (Phases 1–4)

Aligned with [README.md](README.md) roadmap and [todo.md](todo.md):

- **Backend:** REST + WebSocket hub, in-memory store with SQLite write-through ([backend/app/main.py](backend/app/main.py), [backend/app/store.py](backend/app/store.py), [backend/app/hub.py](backend/app/hub.py), [backend/app/db.py](backend/app/db.py)).
- **Simulator vs dwell checker:** Mutually exclusive via `SIMULATOR` in lifespan ([backend/app/main.py](backend/app/main.py))—intentional; consider a dev-only synthetic history seeder for dwell demos.
- **Detector:** CLI, slots config, IoU occupancy, debounce, optional `--track` motion path under [detector/detector/](detector/detector/).
- **Frontend:** Map, markers, theme, WS reconnect pattern under [frontend/src/](frontend/src/).

### 3.2 Partial / skeleton

- **Docker:** [docker-compose.yml](docker-compose.yml) declares `build` with `dockerfile: Dockerfile` per service, but **no `Dockerfile` files exist** in the workspace (verified). Compose is a **skeleton**, not a runnable stack today. The top-level `version: "3.9"` key is obsolete in Compose v2+ (harmless but removable).
- **Phase 5:** [todo.md](todo.md) lists homography, merge rules, `GET /spots?camera=`; [detector/slots.example.json](detector/slots.example.json) documents `camera_id`—multi-camera/homography workflow is **not** complete.

### 3.3 Gaps and bugs worth fixing early (P0 / P1)

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

Anyone who can reach the backend can spoof occupancy. For non-localhost deployment, add at least **HMAC / shared secret** or **mTLS** between detector and API.

**b. Dwell-time inconsistency: `occupied_since_db` vs `query_dwell_db`**

`query_dwell_db` treats both `occupied` and `soon` as starting a dwell segment; `occupied_since_db` only queries `status = 'occupied'`:

```104:125:backend/app/db.py
    for status, recorded_at in rows:
        if status in ("occupied", "soon") and occupied_start is None:
            occupied_start = datetime.fromisoformat(recorded_at)
        ...
async def occupied_since_db(spot_id: str) -> datetime | None:
    ...
            "WHERE spot_id = ? AND status = 'occupied' "
```

If motion promotes a spot to `soon` before dwell logic runs, elapsed time for dwell-based “soon” can be **wrong**. **Fix:** align `occupied_since_db` with the same session-start rules as `query_dwell_db` (and document edge cases for repeated `soon` transitions).

**c. SQLite upsert omits `lat` / `lng` on conflict**

On conflict, only `status`, `confidence`, `camera_id`, `updated_at` are updated—not coordinates:

```49:53:backend/app/db.py
            ON CONFLICT(id) DO UPDATE SET
                status      = excluded.status,
                confidence  = excluded.confidence,
                camera_id   = excluded.camera_id,
                updated_at  = excluded.updated_at
```

If slot calibration changes lat/lng, persisted rows can **drift** until the DB is rebuilt. Low frequency today; worth fixing before Phase 5 calibration churn.

**d. Detector env vs compose**

Compose sets `BACKEND_URL` for the detector; ensure the detector CLI/config has **one** documented source of truth (env override vs `slots.json`) to avoid “works in compose, broken locally” confusion.

**e. Documentation nit**

[README.md](README.md) detector example typo: `sample.mp4--preview` → `sample.mp4 --preview`.

**f. No automated tests, no CI**

No `pytest` / frontend test harness or `.github/workflows` found—high leverage before refactors (IoU, debounce, dwell parsing, WS client behavior).

---

## 4. Gemma 4 capabilities folder — fair assessment

**What the folder is:** A set of **social/demo-style screenshots** under [Gemma 4 capabilities/](Gemma%204%20capabilities/), not Google’s full spec, license text, or reproducible benchmarks on **your** hardware and video.

**Directional narrative from those slides:** Multimodal / local-first stories (e.g. browser WebGPU, `transformers.js`, detector + VLM summarization). The recurring pattern is **fast detector + VLM for language/summary**—not “VLM replaces detector.”

**Fair conclusion for ParkingSpotter:**

| Role | Gemma 4 (or any VLM) |
|------|----------------------|
| Per-frame occupancy, IoU, debounce | **Poor primary fit** — keep YOLO / RF-DETR-class detectors. |
| Motion “soon” via geometry | **Poor substitute** for ByteTrack-style tracks. |
| NL summaries, operator Q&A, incident captions | **Good optional fit** if **gated** (low rate, not per frame). |
| Privacy / scene QA on stored frames | **Possible R&D** — validate latency, false positives, and policy. |

**Recommendation:** Do **not** plan Gemma 4 as the backbone of real-time slot state. If you experiment, use **event-triggered** calls (e.g. occupied + threshold crossed) and measure latency and stability on your cameras. Treat throughput and device claims in screenshots as **unverified** until reproduced on your stack.

---

## 5. Revisiting Opus 4.7 vs GPT 5.4

| Topic | Opus (Apr 16) | GPT (Apr 18) | This reassessment |
|-------|----------------|----------------|-------------------|
| Architecture | Strong | Strong | **Agree** |
| `POST /spots` auth | Strong | Strong | **Agree** |
| Dwell `occupied_since_db` bug | Strong | Strong | **Agree** (confirmed in code) |
| `react-map-gl` “dead weight” | Claimed | **Retracted** | **Retract** — imports are live in `ParkingMap.tsx` / `MapMarkers.tsx` |
| MQTT/NATS before Phase 5 | P1 | “reasonable later” | **Schedule with scale** — not universal P1 for single-detector MVP |
| Gemma 4 | Hybrid detector+VLM | Optional adjunct | **Same hybrid mental model**; caveat demo hype |

---

## 6. Recommended roadmap (refined)

| Priority | Task | Rationale |
|----------|------|-----------|
| **P0** | Authenticate `POST /spots` (HMAC or similar) | Blocks trivial spoofing on exposed deployments. |
| **P0** | Fix `occupied_since_db` vs `query_dwell_db` alignment | Silent correctness bug for yellow-from-dwell. |
| **P0** | Minimal test suite: dwell parsing, upsert semantics, debounce/IoU units | Unlocks safe refactors. |
| **P1** | Add Dockerfiles + make compose runnable; healthchecks, volumes | Matches Phase 7 intent; honest onboarding. |
| **P1** | Phase 5: homography tool, merge rules, `GET /spots?camera=` | Core scale story ([todo.md](todo.md)). |
| **P1** | Fix SQLite upsert to update `lat`/`lng` (or document rebuild) | Avoids stale pins after calibration changes. |
| **P2** | CI (lint, typecheck, smoke backend + short detector clip) | Catches regressions. |
| **P2** | Model experiments: fine-tune on parking data; compare other detectors if needed | Data-driven accuracy. |
| **P2** | Optional MQTT/NATS when multi-detector load warrants | Avoid premature infrastructure. |
| **P3** | Phase 6 synthetic stream | Larger test-infra investment. |
| **P3** | Gemma 4 (or other VLM) prototype: NL popup / operator assist only | Keep off the hot path until proven. |

---

## 7. Things that are already strong (so this is not “all criticism”)

- **Separation of IoU debounce from published status** in the detector (motion “soon” without resetting availability debounce)—good design ([todo.md](todo.md) Phase 4 notes).
- **WebSocket reconnect with backoff + UI offline state**—product-grade detail.
- **Write-through store** (in-memory + SQLite)—right complexity for MVP.
- **`draw_slots.py` calibration**—pragmatic vs brittle auto-slot discovery.
- **`dev.ps1`** cloud-drive workaround—solves a real Windows/npm pain point.

---

## 8. Closing

- **Idea:** Still strong; “soon” remains the differentiator.
- **Stack:** Appropriate; **no wholesale replacement** recommended.
- **Codebase:** Phases 1–4 are reflected in the repo; Docker and Phase 5 are not at the level compose implies.
- **Gemma 4 folder:** Directional only; VLMs **adjacent** to the detector, not instead of it.

Next concrete wins: **secure ingest**, **dwell fix**, **tests**, **Docker reality**, then **Phase 5**.

---

*Internal reassessment note; not a substitute for production security review or formal model benchmarking.*
