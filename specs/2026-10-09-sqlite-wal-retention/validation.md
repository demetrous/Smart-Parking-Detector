# Validation: SQLite durability and history retention (Phase 2, `R0.2`)

Ready to merge when everything below holds.

## Automated

- [ ] `python -m pytest` exits 0 from the repo root (no GPU, camera or weights)
- [ ] `cd frontend && npm run lint && npm run build` exits 0 (no frontend change expected)
- [ ] CI is green on the PR

### Required test coverage

- [ ] All db operations go through the shared helper (no other `aiosqlite.connect` in `backend/app/`)
- [ ] `journal_mode` is `wal` after `init_db`; `busy_timeout` is `5000` on helper connections
- [ ] A reader is not blocked by another connection's exclusive write transaction (WAL)
- [ ] A writer waits for a briefly held lock instead of failing with `database is locked`
- [ ] Pruning removes completed sessions that ended before the cutoff
- [ ] Pruning preserves a spot's open session regardless of age
- [ ] Pruning preserves a session that straddles the cutoff
- [ ] Dwell stats for sessions inside the retention window are unchanged by pruning
- [ ] Pruning is idempotent; retention `0` deletes nothing
- [ ] Startup pass runs in `lifespan`; daily loop survives a failing pass
- [ ] Existing dwell, upsert, seed and pilot API tests pass unchanged

## Manual

- [ ] Start the backend against a copy of a real `parking.db`: `parking.db-wal` and `parking.db-shm` appear while it runs (SQLite removes them on a clean shutdown), and `SELECT COUNT(*) FROM spot_history` drops only by rows from sessions that ended before the cutoff (the prune count is logged at INFO, which plain `uvicorn` does not print by default)
- [ ] `sqlite3 parking.db "PRAGMA journal_mode;"` prints `wal`
- [ ] With the simulator on for a few minutes, no `database is locked` errors in the log
- [ ] `GET /spots/{id}/dwell` returns the same numbers before and after a restart that pruned nothing new

## Guardrail check

- [ ] `POST /spots` HMAC code and tests untouched
- [ ] Single-process assumption unchanged (no workers, no cross-process state)
- [ ] No new dependencies
- [ ] No frontend changes

## Definition of done

All automated and manual checks pass, a separate review session has checked the
diff against this file, `README.md` and `backend/README.md` document
`PARKINGSPOTTER_HISTORY_RETENTION_DAYS` and the WAL backup note, and Phase 2
boxes are ticked in `specs/roadmap.md` and `todo.md`.
