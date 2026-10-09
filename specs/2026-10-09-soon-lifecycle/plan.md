# Plan: "Soon" lifecycle correctness (Phase 3, `R0.3`)

Each group is independently committable. Run `python -m pytest` after each
group.

---

## Group 1: Promotion tracking in `SpotStore`

1. Add a `DwellPromotion` dataclass (`promoted_at`, `demoted_at: datetime | None`)
   and `_promotions: dict[str, DwellPromotion]`.
2. Add `_base: dict[str, Spot]` beside `_canonical` (published). Every writer
   sets the base, then derives the published spot with one `_compose(base,
   promotion)` function implementing the table in `requirements.md`.
3. Clear a spot's promotion when its base becomes `available`, and on
   `upsert_canonical`.
4. `bootstrap_from_db` fills `_base` and `_canonical` identically (no
   promotions after a restart).

## Group 2: Writer lock and composition in the write paths

5. Add `_write_lock`; `apply_detector_update` and `upsert_canonical` hold it
   from the start of the update through the DB write. The in-memory `_lock`
   stays for short dict access, so readers never wait on SQLite.
6. `apply_detector_update` (both the `cameraId` and the legacy path) computes
   the base as today, composes with the promotion, and reports `changed` on the
   published spot.

## Group 3: Promote / demote API

7. `dwell_snapshot()` returns `(spot_id, base_status, promotion)` for every
   spot.
8. `promote_dwell(spot_id, now)`: no-op unless base is `occupied` and no
   promotion exists; otherwise record it, publish, persist, return
   `(changed, published)`.
9. `demote_dwell(spot_id, now)`: no-op unless an active promotion exists;
   otherwise set `demoted_at`, publish, persist if changed, return
   `(changed, published)`.

## Group 4: Dwell checker

10. `soon_demote_factor()` reads `SOON_DEMOTE_FACTOR` (default `1.3`, invalid
    → warning + default).
11. `dwell_check_once(now=None, *, threshold, demote_factor, min_count)`:
    - skip demoted spots, and spots without an active promotion whose base is
      not `occupied`
    - skip when dwell stats are missing or below `min_count`, or no open session
    - no promotion and `threshold × mean ≤ elapsed < demote_factor × mean`
      → `promote_dwell`
    - active promotion and `elapsed ≥ demote_factor × mean` → `demote_dwell`
    - broadcast `spot.update` when the published spot changed; log at INFO
12. `dwell_checker_loop` logs one warning at start if
    `demote_factor ≤ threshold`, then sleeps, calls `dwell_check_once`, and
    logs and continues on any exception.

## Group 5: App logging

13. `_configure_app_logging()` in `main.py`, called first in `create_app()`:
    attach a stream handler to the `app` logger only when it and the root
    logger have no handlers; level from `PARKINGSPOTTER_LOG_LEVEL` (default
    `INFO`, invalid → warning + `INFO`).

## Group 6: Tests

14. New `backend/tests/test_soon_lifecycle.py` (deterministic `now`, seeded
    `spot_history`, captured broadcasts):
    - `occupied → soon → occupied` through `dwell_check_once` at
      `0.7×`, `<1.3×`, `≥1.3×` mean; exactly two broadcasts
    - no re-promotion on later passes after demotion
    - a same-status observation keeps an active promotion; no broadcast
    - a different camera winning the merge with `occupied` keeps the promotion
    - an `available` observation clears the promotion; the next `occupied`
      publishes `occupied`
    - detector motion `soon` passes through; no promotion is created for it;
      demoting a promotion while the base is `soon` publishes nothing
    - elapsed already past the demote point (restart) → no promotion
    - `promote_dwell` after the base went `available` is a no-op (race)
    - `upsert_canonical` clears a promotion
    - `soon_demote_factor()` default / invalid; `demote_factor ≤ threshold`
      never promotes
    - dwell stats unchanged by promotion/demotion history rows
    - checker loop survives a failing pass
    - logging setup: handler added only when unconfigured; level from env

## Group 7: Docs and close-out

15. `README.md`: env table (`SOON_DEMOTE_FACTOR`, `PARKINGSPOTTER_LOG_LEVEL`),
    the dwell walkthrough mentions demotion.
16. `backend/README.md`: env table, "soon" lifecycle note, test coverage list.
17. Tick Phase 3 in `specs/roadmap.md` (with the spec link) and `R0.3`
    Progress in `todo.md`; update the `todo.md` index.
