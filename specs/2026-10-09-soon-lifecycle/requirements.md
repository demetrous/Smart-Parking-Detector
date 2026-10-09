# Requirements: "Soon" lifecycle correctness (Phase 3, `R0.3`)

Source: `todo.md` § `R0.3` "Soon" lifecycle correctness. Roadmap:
`specs/roadmap.md` Phase 3. Origin: finding 2 in
`docs/PROJECT-REVIEW-2026-07.md` ("soon" never demotes, and the dwell checker
and the multi-camera merge both write canonical state with no precedence).

## Scope

Make the yellow pin trustworthy. A dwell-time promotion must end when the
prediction misses, and the dwell checker must stop racing the merge layer for
canonical state.

### Today

- `dwell_checker_loop` (`backend/app/main.py`) reads a snapshot of canonical
  spots, awaits two DB queries per spot, then writes a copy of the *old*
  snapshot with `status="soon"` through `store.upsert_canonical`. Anything that
  happened to the spot in between (car left, another camera won the merge) is
  overwritten.
- The next detector observation for that spot recomputes the merge from
  observations and silently replaces the promotion with `occupied`.
- If the car stays, the promotion never ends; the pin stays yellow forever.
- Canonical persistence (`upsert_spot_db`) runs after the store lock is
  released, so two writers can append `spot_history` rows out of order.

### In scope

| Area | Change |
|------|--------|
| `backend/app/store.py` | Keep the **base** canonical (merge result or direct write) separately from the **published** canonical. Track dwell promotions per spot (`promoted_at`, `demoted_at`). Published status is composed from base + promotion by one rule. |
| `backend/app/store.py` | `promote_dwell(spot_id, now)` and `demote_dwell(spot_id, now)`: re-check base state under the lock, update bookkeeping, persist and return the published spot. |
| `backend/app/store.py` | A writer lock so compute + persist of canonical state is serialized across detector ingest, dwell checker, simulator and seeds (history rows land in the same order as in-memory changes). |
| `backend/app/main.py` | Dwell checker uses the store API, adds the demotion rule and `SOON_DEMOTE_FACTOR`, logs promotions/demotions, and survives a failing pass. |
| `backend/app/main.py` | App-level logging: `app.*` INFO lines (retention, promotions, demotions, warnings) print under plain `uvicorn`. |
| Tests | New `backend/tests/test_soon_lifecycle.py`. |
| Docs | `README.md`, `backend/README.md`: new env vars, "soon" lifecycle description. |

### Composition rule (deterministic)

Per spot, with `base` = merged canonical from observations (or the latest
direct write) and `promotion` = this spot's dwell bookkeeping:

| Base status | Promotion state | Published status |
|-------------|-----------------|------------------|
| `occupied` | active | `soon` |
| `occupied` | none, or demoted | `occupied` |
| `soon` (detector motion) | any | `soon` (passes through unchanged) |
| `available` | — (cleared) | `available` |

Published `updatedAt` is the later of the base `updatedAt` and the last
promotion/demotion time, so a client never sees time go backwards.

### Promotion lifecycle

| Event | Effect |
|-------|--------|
| Checker: base `occupied`, no promotion, `SOON_THRESHOLD × mean ≤ elapsed < SOON_DEMOTE_FACTOR × mean` | Promotion created; publish `soon`; broadcast |
| Checker: active promotion, `elapsed ≥ SOON_DEMOTE_FACTOR × mean` | Promotion marked demoted; publish base (`occupied`); broadcast if published status changed |
| New observation, base still `occupied` | Promotion kept; published stays `soon`; no broadcast |
| New observation, base `soon` (motion) | Promotion kept; published `soon` (no change in bookkeeping) |
| New observation, base `available` | Promotion (and demoted marker) cleared silently; publish `available` (normal flow) |
| Simulator / seed write (`upsert_canonical`) | Promotion cleared; the written spot is published as-is |
| Backend restart | Bookkeeping is in memory only and starts empty; the checker re-promotes on its next pass if still inside the window |

`elapsed` is measured from the start of the spot's current occupancy session
(`occupied_since_db`), as today. `mean` and the sample-count gate
(`DWELL_MIN_COUNT`) are unchanged.

### New configuration

| Variable | Service | Default | Meaning |
|----------|---------|---------|---------|
| `SOON_DEMOTE_FACTOR` | backend | `1.3` | Multiple of mean dwell after which a dwell-promoted spot goes back to `occupied`. Must be greater than `SOON_THRESHOLD`; if it is not, a warning is logged and dwell promotions are effectively off. Invalid values log a warning and use `1.3`. |
| `PARKINGSPOTTER_LOG_LEVEL` | backend | `INFO` | Level for the backend's own `app.*` loggers. Invalid values log a warning and use `INFO`. |

### Out of scope

- Persisting promotion state across restarts (no schema change).
- Changing how dwell statistics are computed (time-bucketed dwell is `R2.2`).
- Detector-side motion "soon" logic (`detector/detector/tracker.py`).
- Ordering of WebSocket broadcasts between two concurrent publishers (same as
  today between two detector posts); the frontend and `spot_history` order is
  fixed by the writer lock up to the broadcast call.
- ~~Spots that exist only as a `spots` row with no camera observations (demo
  seeds, legacy posts without `cameraId`): a persisted `soon` for those is
  bootstrapped as base `soon`, as today.~~ Moved in scope by the post-merge
  review, see "Follow-up" below.
- Any change to `POST /spots` HMAC, the projects API or the frontend.

## Decisions

- **No re-promotion after a demotion within one occupancy session** (Dmitrii,
  2026-10-09). Without it the checker would promote again on the next tick,
  because elapsed time is still past the threshold, and the pin would flicker.
  Two guards: the demoted marker in `SpotStore`, and the promotion window's
  upper bound (`elapsed < SOON_DEMOTE_FACTOR × mean`), which also covers a
  restart that lost the marker. The marker clears when the base goes
  `available`.
- **Promotion state is in memory only** (Dmitrii, 2026-10-09). Matches the
  single-process design (`AGENTS.md` #9). After a restart the checker rebuilds
  promotions from the window rule.
- **Simulator and seed writes clear any promotion** (Dmitrii, 2026-10-09).
  They write a complete spot state; mixing it with dwell bookkeeping would be
  undefined.
- **Promotion only from base `occupied`.** A detector motion `soon` is already
  yellow; promoting it would add bookkeeping that the composition rule ignores.
  An active promotion is kept while the base is motion-`soon` and demotes on
  schedule; that demotion changes nothing published while the base is `soon`.
- **Promote/demote re-check under the lock.** The checker passes only the spot
  id; the store reads the current base when it applies the change. If the base
  is no longer `occupied` (car left while the checker was querying the DB), the
  promotion is a no-op.
- **Writer lock across persist.** Canonical writers (`apply_detector_update`,
  `upsert_canonical`, `promote_dwell`, `demote_dwell`) hold a separate writer
  lock through their DB write, so `spot_history` order matches in-memory order.
  Readers (`list_canonical`, `get`, `list_for_camera`) only take the short
  in-memory lock and never wait on SQLite.
- **`spot_history` records published changes.** Promotion and demotion rows
  (`soon`, `occupied`) are appended as today. Both are active-session statuses,
  so dwell sessions and stats are unchanged by them. The pilot (Phase 6) can
  read when yellow was actually shown.
- **Demotion of an active promotion needs dwell stats.** If `mean` is missing or
  `count < DWELL_MIN_COUNT` at check time, the checker leaves the spot alone
  (cannot evaluate either bound).
- **Checker survives errors.** Each pass is wrapped; an exception is logged and
  the loop continues (deferred from Phase 2).
- **Logging.** `create_app()` attaches one stream handler to the `app` logger
  only when neither it nor the root logger has handlers, which is the plain
  `uvicorn app.main:app` case. A user `--log-config` or test harness that
  configures the root logger is left alone, so there are no duplicate lines.
- **No new dependencies.**

## Context

- Guardrails (`AGENTS.md`): single-process backend (#9): in-memory promotion
  bookkeeping is correct only with one worker. HMAC on `POST /spots` untouched.
  Demo freeze: no frontend change.
- Routing (`docs/MODEL-ROUTING.md`): cross-cutting correctness (dwell model,
  merge semantics), frontier tier. Implemented with Opus 5.5 at high effort.
- Patterns to follow: `SpotStore` lock usage and `_canonical_fields_differ`,
  `_spawn_background` and `_env_truthy` in `main.py`, the
  `monkeypatch.setattr(db, "DB_PATH", ...)` fixtures, `history_recorded_at`
  for deterministic history in tests.
- Files likely to change: `backend/app/store.py`, `backend/app/main.py`, new
  `backend/tests/test_soon_lifecycle.py`, `README.md`, `backend/README.md`,
  `specs/roadmap.md`, `todo.md`.

## Follow-up (post-merge review, 2026-10-09)

The verification review (`/mnt/project-files/sdd-phase3/phase3-verification-review.md`)
found two gaps; Dmitrii chose to fix both in one follow-up PR.

- **Session guard.** `SpotStore` keeps a per-spot occupancy-session counter,
  bumped when the base enters `available` (detector merge or direct write) and
  on bootstrap. `dwell_snapshot` returns it; the checker passes it back to
  `promote_dwell` / `demote_dwell`, which are no-ops if it changed. Without it,
  a car that left and was replaced by a new one while the checker was querying
  SQLite was promoted on the previous car's elapsed time and stayed yellow until
  `SOON_DEMOTE_FACTOR` × mean.
- **Restart.** A `spots` row that is `soon` with no camera observations is
  restored as base `occupied` when its open `spot_history` session saw
  `occupied` before (a dwell promotion, or a legacy motion `soon` without
  `cameraId`, which shows `occupied` until its next post). A `soon` that started
  its session (demo seed `C8`) is kept. At bootstrap, any spot whose published
  status differs from its `spots` row (these restores, or a camera-backed spot
  whose merge no longer says `soon`) is persisted and logged, so `spot_history`
  matches what clients see.

