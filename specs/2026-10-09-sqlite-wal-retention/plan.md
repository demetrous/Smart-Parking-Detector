# Plan: SQLite durability and history retention (Phase 2, `R0.2`)

Each group is independently committable. Run `python -m pytest` after each
group.

---

## Group 1: Shared connection helper

1. Add `connect()` (async context manager) to `backend/app/db.py`: open
   `aiosqlite.connect(DB_PATH)`, run `PRAGMA busy_timeout=5000`, then, the
   first time this path is seen in the process, `PRAGMA journal_mode=WAL`;
   log one warning if the result is not `wal`.
2. Route every existing operation through it: `init_db`,
   `append_spot_history_row`, `upsert_spot_db`, `load_spots_db`,
   `upsert_observation_db`, `load_observations_db`, `query_dwell_db`,
   `occupied_since_db`. No other module opens SQLite directly.

## Group 2: Retention core

3. Add `history_retention_days()`: reads
   `PARKINGSPOTTER_HISTORY_RETENTION_DAYS`, default `90`, `0` = disabled,
   invalid or negative → warning + default.
4. Add `prune_history_db(retention_days, *, now=None) -> int`:
   - return `0` immediately when `retention_days <= 0`
   - cutoff = `now - retention_days`
   - for each `spot_id` with rows older than the cutoff: find the latest
     `available` row before the cutoff; delete that spot's rows strictly older
     than it; commit per spot
   - return the total number of rows deleted

## Group 3: Wiring

5. In `lifespan`, after `init_db()`: run one prune pass with the configured
   retention, log the count, catch and log any exception.
6. Add `history_retention_loop()`: sleep 24 h, prune, log; catch and log
   exceptions and keep looping. Spawn it with `_spawn_background` when
   retention is enabled.

## Group 4: Tests

7. New `backend/tests/test_sqlite_wal_retention.py`:
   - after `init_db`, a raw connection reports `journal_mode = wal`
   - a helper connection reports `busy_timeout = 5000`
   - no app module other than the helper calls `aiosqlite.connect`
   - WAL in effect: a reader returns promptly while another connection holds
     an exclusive write transaction
   - busy_timeout in effect: a write waits for a short-held lock and succeeds
   - pruning removes completed sessions older than the cutoff entirely
   - pruning keeps a session that straddles the cutoff in full
   - pruning keeps an open session older than the cutoff; `occupied_since_db`
     unchanged
   - dwell stats for sessions ending inside the window are identical before
     and after pruning; a second prune deletes nothing
   - retention `0` deletes nothing; env parsing (default, `0`, invalid)
   - startup pass: old rows seeded before app start are pruned by `lifespan`
   - the loop keeps running after a prune raises

## Group 5: Docs and close-out

8. `README.md` backend env table and `backend/README.md` env table: add
   `PARKINGSPOTTER_HISTORY_RETENTION_DAYS`.
9. `backend/README.md`: Database section describes retention and WAL; backup
   note uses `.backup` and mentions the `-wal`/`-shm` files; test coverage
   list updated.
10. Tick Phase 2 items in `specs/roadmap.md` (with the spec link) and `R0.2`
    Progress in `todo.md`; mark `R0.2` done in the `todo.md` index.
