# Validation: "Soon" lifecycle correctness (Phase 3, `R0.3`)

Ready to merge when everything below holds.

## Automated

- [ ] `python -m pytest` exits 0 from the repo root (no GPU, camera or weights)
- [ ] `cd frontend && npm run lint && npm run build` exits 0 (no frontend change expected)
- [ ] CI is green on the PR

### Required test coverage (from `todo.md` acceptance criteria)

- [ ] Sequence `occupied → [dwell promotion] soon → car stays past demote factor → occupied` is covered by a test
- [ ] A new observation for the same spot no longer silently reverts an active dwell promotion
- [ ] Detector motion-`soon` is unaffected by promotion bookkeeping
- [ ] `SOON_DEMOTE_FACTOR` documented alongside `SOON_THRESHOLD` (`README.md`, `backend/README.md`)

### Additional coverage (from this spec's decisions)

- [ ] No re-promotion after a demotion in the same occupancy session
- [ ] An `available` observation clears the promotion; the next session starts clean
- [ ] Promotion against a base that changed under the checker is a no-op
- [ ] Simulator/seed writes clear promotions
- [ ] Past the demote point at startup (no bookkeeping) → no promotion
- [ ] Dwell stats are unchanged by promotion/demotion history rows
- [ ] Checker loop survives a failing pass
- [ ] Existing merge, dwell, upsert, pilot API, auth and retention tests pass unchanged

## Manual

Run the backend locally against a **fresh** database with the simulator off
and the dwell demo seed. The demo seed starts spot `C1` as `occupied` at
startup and gives it three past sessions (400, 520, 440 s; mean ≈ 453 s), so
with the defaults `C1` turns yellow after ≈ 317 s and red again after
≈ 589 s, with no detector running:

```bash
cd backend
DB_PATH=phase3-check.db SIMULATOR=false PARKINGSPOTTER_SEED_DWELL_DEMO=true \
DWELL_CHECK_INTERVAL=5 uvicorn app.main:app
```

(PowerShell: set the same variables with `$env:NAME = "value"` first.)

- [ ] Startup prints `app.*` INFO lines under plain `uvicorn` (history retention line)
- [ ] After ≈ 317 s `C1` turns yellow on the map; an INFO line logs the promotion
- [ ] After ≈ 589 s `C1` turns red again; an INFO line logs the demotion; it does not flicker back to yellow on later passes
- [ ] Optional, with `PARKINGSPOTTER_SHARED_SECRET` set and signed posts (or the detector): repeated `occupied` posts for a promoted spot keep it yellow; an `available` post turns it green
- [ ] `PARKINGSPOTTER_LOG_LEVEL=WARNING` hides the INFO lines
- [ ] Delete `phase3-check.db*` afterwards

## Guardrail check

- [ ] `POST /spots` HMAC code and tests untouched
- [ ] Single-process assumption unchanged (promotion state is in-process only)
- [ ] No new dependencies
- [ ] No frontend changes

## Definition of done

All automated and manual checks pass, a separate review session has checked
the diff against this file, `README.md` and `backend/README.md` document
`SOON_DEMOTE_FACTOR` and `PARKINGSPOTTER_LOG_LEVEL`, and Phase 3 boxes are
ticked in `specs/roadmap.md` and `todo.md`.
