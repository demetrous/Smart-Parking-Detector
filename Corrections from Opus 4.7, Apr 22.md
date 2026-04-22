# Corrections from Opus 4.7 — April 22, 2026

Review target: work done by **Composer 2** in commits `d07957a`, `7ace891`, `6506682`, `3a68b13`
(roadmap items `P0.1`–`P2.1` plus `P2.3`).

## Summary

**Overall verdict: Composer 2 did a good job.** The P0–P2 roadmap work is
coherent, the three-service shape is preserved, and the acceptance criteria in
`todo.md` are met by the implementation. I ran the full suite
(`pytest`, `npm run lint`, `npm run build`) — 17/17 backend + detector tests
pass, frontend lints clean, and the production build succeeds. The backend also
imports and instantiates cleanly.

Everything below is follow-up polish. None of it invalidates the work that was
marked completed, but several items are real correctness / hygiene issues that
should be fixed before a production deployment, and a couple of them contradict
the acceptance language in the roadmap itself.

Items are ordered roughly by severity.

---

## 1. Background tasks are started without holding a reference (real bug)

**File:** `backend/app/main.py`, lines 152–155

```python
if _simulator_enabled():
    asyncio.create_task(simulator_loop())
if _dwell_checker_enabled():
    asyncio.create_task(dwell_checker_loop())
```

`asyncio.create_task` returns a task whose reference must be held, otherwise
the task can be garbage-collected mid-execution (the running event loop only
keeps **weak** references). This is a well-known footgun — see the Python docs
for `asyncio.create_task`.

In practice this often "works" because each loop re-awaits `asyncio.sleep`,
which reschedules via the loop's ready queue, but the Python docs explicitly
warn that "tasks may disappear mid-execution."

**Fix:** keep a module-level set (or store on `app.state`) and remove on done.

```python
_background_tasks: set[asyncio.Task] = set()

def _spawn(coro):
    t = asyncio.create_task(coro)
    _background_tasks.add(t)
    t.add_done_callback(_background_tasks.discard)
    return t
```

and use `_spawn(simulator_loop())` / `_spawn(dwell_checker_loop())`.

---

## 2. `frontend/Dockerfile` is not reproducible (real bug)

**File:** `frontend/Dockerfile`, lines 11–12

```dockerfile
COPY package.json ./
RUN npm install
```

The lockfile `package-lock.json` is **not** copied, and the install uses
`npm install` rather than `npm ci`. This means the image may resolve different
transitive dependency versions than local dev or CI, which defeats the
purpose of the lockfile. CI uses `npm ci` correctly; Docker should match.

**Fix:**

```dockerfile
COPY package.json package-lock.json ./
RUN npm ci
```

This also makes the build faster and cache-friendlier.

---

## 3. `backend/tests/test_spots_auth.py` is missing the "malformed timestamp" case

The `P0.1` acceptance criteria in `todo.md` say:

> Reject missing, stale, malformed, or invalid signatures with `401` or `403`.

The test suite covers **valid**, **missing headers**, **invalid signature**,
and **stale**. It does **not** cover **malformed timestamp**, even though
`backend/app/auth.py:_parse_timestamp` has a dedicated branch that raises
`401 "Malformed detector timestamp"`.

**Fix:** add a short test that sends a garbage `X-ParkingSpotter-Timestamp`
(for example `"not-a-date"`) and asserts `401` with
`detail == "Malformed detector timestamp"`. The branch currently has no
regression coverage at all.

---

## 4. Multi-camera merge has no eviction for stale/offline cameras

**Files:** `backend/app/store.py`, `backend/app/merge.py`

`merge_canonical_for_spot` always picks the highest-priority camera that
currently has **any** observation in memory. If the priority camera stops
posting (crash, network partition, power loss), its last observation wins the
merge indefinitely, even when lower-priority cameras keep posting fresh data
for minutes or hours.

This is consistent with `P1.3`'s "deterministic merge rules, not heuristics"
wording, and the roadmap does not explicitly require eviction. However, it's
a footgun in production: **a dead camera looks perfectly healthy to the merge
layer.**

**Suggestion (additive, non-breaking):** add a `max_age_seconds` field to
`MergeConfig` (default very large, so behavior is unchanged when not set) and
in `merge_canonical_for_spot` skip observations whose
`updatedAt` is older than `now - max_age_seconds`. This preserves determinism
— eviction is still config-driven, not heuristic.

---

## 5. `upsert_spot_db` and `spot_history` can regress in time under merge

**Files:** `backend/app/store.py`, `backend/app/db.py`

In the multi-camera path, `apply_detector_update` writes
`upsert_spot_db(merged)` using `merged.updatedAt`, which is the chosen
observation's timestamp — not wall-clock now. In the normal happy path this
is fine because the winner is usually the newest observation of the
winning camera. But:

- If the merge priority flips to a camera whose last observation is older
  than the existing canonical, the `spots` row's `updated_at` can regress
  backwards in time.
- More subtly, the appended `spot_history` row also gets that older
  `recorded_at`, so the history is not guaranteed to be append-chronological.

Today the guard `_canonical_fields_differ` (which ignores `updatedAt`)
prevents most wasted writes. But once any observable field flips, you can
still record a history event with an older timestamp than the previous one.

**Fix:** when appending `spot_history`, record **wall-clock now**, not the
observation's `updatedAt`. The `spots` row can keep `updatedAt` from the
observation (that is a legitimate "as-of" field), but the history is an event
log and should be monotonic.

```python
# in upsert_spot_db, for the history insert:
(spot.id, spot.status, spot.confidence, datetime.now(timezone.utc).isoformat())
```

This also fixes a second-order hazard: `query_dwell_db` / `occupied_since_db`
sort by `recorded_at ASC` and compute session boundaries from that ordering.
Out-of-order inserts can silently corrupt dwell stats.

---

## 6. `spot_history` has no index on `spot_id`

**File:** `backend/app/db.py`, `_CREATE_HISTORY`

Both `query_dwell_db` and `occupied_since_db` run
`SELECT ... FROM spot_history WHERE spot_id = ? ORDER BY recorded_at ASC`.
With no index on `spot_id`, each query scans the whole table.

For demo volumes this is fine. For a small pilot with one camera posting one
status change per minute over a month, `spot_history` is already ~40 k rows;
with multiple cameras and full histories it grows linearly and the dwell
checker loop (`DWELL_CHECK_INTERVAL=15s`, full scan per occupied spot) will
start to dominate.

**Fix:** add in `init_db`:

```sql
CREATE INDEX IF NOT EXISTS idx_spot_history_spot_id_time
  ON spot_history (spot_id, recorded_at);
```

Cheap, backward-compatible, and makes the checker loop O(log n) per spot.

---

## 7. `SpotStore.list_for_camera` has an unused loop variable

**File:** `backend/app/store.py`, lines 92–98

```python
return [
    obs.model_copy()
    for (sid, cam), obs in self._observations.items()
    if cam == camera_id
]
```

`sid` is unused and some linters will flag it. Prefer `(_, cam)` or destructure
only what you use. Not a bug — purely cosmetic.

---

## 8. Detector Dockerfile has no `.dockerignore` and bakes in a blank sample video

**File:** `detector/Dockerfile`

Two minor issues:

1. `COPY detector ./detector` copies `__pycache__/`, `tests/`, and test
   fixtures into the production image. There's no `.dockerignore`, so every
   developer's bytecode cache ends up in the shipped image.
2. Line 24 builds a 30-frame black MP4 at image-build time so the optional
   `--profile detector` compose run has something to open. This is reasonable
   for smoke tests, but because the frames are all zeros, YOLO never detects
   anything — the detector loops forever reporting the initial state. The
   healthcheck (`pgrep -f "python -m detector.main"`) passes regardless, so
   this looks healthy in Compose even when it's effectively a no-op.

**Fixes:** add a `detector/.dockerignore` with `__pycache__/`, `tests/`,
`*.pyc`, `.pytest_cache/`. Consider a small real clip committed to the repo
(or a noisier generated clip — e.g. a moving rectangle) so the demo shows
state transitions rather than a frozen state.

---

## 9. `backend/app/main.py` calls `create_app()` at import time

**File:** `backend/app/main.py`, line 226

`app = create_app()` runs at import, which means any test that imports
`main` (including `conftest`-free imports) instantiates a full FastAPI app
with a `CORSMiddleware`, reads env vars at that moment, and wires the route
handlers — only to have the fixture throw away that instance and construct a
second one.

Not a bug, but slightly wasteful and can surprise: if `CORS_ORIGINS` /
`PARKINGSPOTTER_SHARED_SECRET` are set differently at import vs fixture-time,
the module-level `app` and the per-test `app` diverge in subtle ways.

**Suggestion (non-breaking):** keep the `app = create_app()` line (ASGI
servers expect `app.main:app`), but guard it:

```python
app = create_app() if os.getenv("PARKINGSPOTTER_SKIP_APP_AT_IMPORT") != "1" else None
```

…or restructure so tests import `create_app` from a factory module only.

---

## 10. `dwell_checker_loop` has no direct test coverage

The whole purpose of `P1` was to make yellow "soon" pins reachable via dwell
history, and `P2.3` added a seeding path specifically so the signal is
demonstrable. But there is no backend test that actually exercises
`dwell_checker_loop` — it's monkey-patched to a no-op in `test_spots_auth.py`
and never invoked elsewhere.

`query_dwell_db` and `occupied_since_db` are well tested. The promotion rule
(`elapsed >= _SOON_THRESHOLD * dwell["mean"]` ⇒ broadcast `soon`) is not.

**Suggestion:** a unit test that:

1. seeds completed history (use `seed_dwell_demo_sparse`),
2. upserts an `occupied` canonical spot whose current session is older than
   `_SOON_THRESHOLD * mean`,
3. calls **one iteration** of the loop's body (extracted into a pure helper)
   and asserts the broadcast and canonical transition to `soon`.

The extraction of the body to a pure helper is small and makes the whole
thing reviewable.

---

## 11. Minor: `_FALLBACK_CONFIG` silently hides config typos

**File:** `detector/detector/main.py`, lines 31 and 100–102

```python
except FileNotFoundError:
    log.warning("Config file %r not found — running with no slots (inference only)", args.config)
    cfg = _FALLBACK_CONFIG
```

If someone passes `--config slotss.json` (typo), the detector **does not
exit** — it proceeds with zero slots and runs YOLO forever with nothing to
publish. That wastes cycles and silently fails.

**Suggestion:** keep the fallback only for the default path (`slots.json`
missing = first-run OK), but treat an **explicit** non-default `--config`
that doesn't exist as an error.

---

## 12. Nits

These are not bugs, just noise worth cleaning up on the next pass:

- `detector/detector/auth.py:signed_headers` calls `current_shared_secret()`
  on every POST. It's cheap, but caching `secret = current_shared_secret()`
  at detector startup and passing it through is clearer and avoids per-POST
  env reads.
- `backend/app/auth.py` returns `HTTPException(503)` when the secret is not
  configured. `503` is odd — a missing server-side secret is a deploy-time
  configuration error, not a transient unavailability. Prefer failing at
  `lifespan` startup (`require_secret_or_raise()`) rather than at first
  `POST`.
- `backend/app/main.py:dwell_checker_loop` computes
  `datetime.now(timezone.utc) - since` inside the loop but does not clamp
  the result; a clock skew or a recent backwards-in-time history row (see
  item 5) could produce a negative `elapsed` and silently never trigger.
  A defensive `elapsed = max(0.0, elapsed)` would be kind.
- `backend/tests/conftest.py` inserts `BACKEND_ROOT` into `sys.path`. This
  is already handled by `pyproject.toml` (`pythonpath = [".", "backend"]`),
  so the conftest manipulation is redundant and can be removed.
- `frontend/src/state/SpotsProvider.tsx` computes `byId: new Map(...)` on
  every spots mutation but nothing in the codebase reads `byId`. Either
  start using it (e.g. in `MapMarkers` popup lookup) or drop it.
- `detector/source.py` — with `skip_frames=2`, `frame_idx % self.skip_frames == 0`
  starts yielding at frame 2, skipping the first emitted frame. Harmless,
  but calling it "every other frame starting with frame 2" is surprising;
  most readers expect "every other frame starting with frame 1".

---

## What I verified end-to-end

- `python -m pytest` (root) → **17 passed** in ~2 s.
- `npm run lint` (frontend) → clean, no warnings.
- `npm run build` (frontend) → succeeds; TypeScript check passes; Vite
  produces `dist/`.
- `from backend.app.main import create_app; create_app()` → routes wired as
  expected: `/health`, `/spots` (GET+POST), `/spots/{spot_id}/dwell`, `/ws`.
- `.gitignore` correctly excludes `*.db`; the stray local `parking.db` files
  are not tracked.
- Roadmap claims in `todo.md` for `P0.1`–`P2.1` and `P2.3` match the code —
  no items are marked complete that are actually missing in the source.

---

## What I did **not** find (good signs)

- No dependency-pin regressions in `backend/requirements.txt` or
  `detector/requirements.txt`.
- No secrets committed. The docker-compose `local-dev-secret-change-me`
  default is clearly a dev placeholder and documented as such in
  `detector/README.md` and `backend/README.md`.
- The occupancy-session helper (`_occupancy_sessions`) is used by both
  `query_dwell_db` and `occupied_since_db` — `P0.2`'s "one helper" rule is
  actually respected.
- The HMAC signature contract (`timestamp + "." + raw_body`, constant-time
  compare, `abs((current - parsed).total_seconds()) > max_age` so both stale
  **and** future-dated are rejected) is correct.
- `upsert_spot_db` does update `lat` / `lng` on conflict (`P1.2`), and the
  regression test exercises the repost-with-new-coords case.
- Homography round-trip is tested against the reference points, not just
  smoke-tested.

---

## Recommended follow-up order

If you only do three things from this doc, do:

1. **Item 2** (`npm ci` + lockfile in `frontend/Dockerfile`) — trivially
   fixable, immediately improves reproducibility.
2. **Item 1** (hold references to the asyncio background tasks) — small
   change, removes a latent production hazard.
3. **Item 5 + item 6** together (history uses wall-clock `now`, plus the
   `spot_history(spot_id, recorded_at)` index) — both protect the dwell
   pipeline, which is the most analytically load-bearing part of the
   backend.

Everything else is additive polish.
