# Requirements: SQLite durability and history retention (Phase 2, `R0.2`)

Source: `todo.md` § `R0.2` SQLite durability and history retention. Roadmap:
`specs/roadmap.md` Phase 2. Origin: finding 5 in
`docs/PROJECT-REVIEW-2026-07.md` (no WAL, no busy_timeout,
connection-per-operation, unbounded `spot_history`).

## Scope

Prevent `database is locked` incidents under pilot load and stop
`spot_history` from growing without bound.

### In scope

| Area | Change |
|------|--------|
| `backend/app/db.py` | One connection helper, `db.connect()`, used by every database operation. It sets `PRAGMA busy_timeout=5000` on each connection and switches the database to `journal_mode=WAL` once per database file. |
| `backend/app/db.py` | `prune_history_db(retention_days)`: deletes old `spot_history` rows by whole session, never touching a spot's current open session. |
| `backend/app/main.py` | One retention pass at startup (after `init_db`, before seeding and background loops) and a daily background task. |
| Docs | New env var, WAL side files and backup note, `spot_history` no longer "append-only forever". |

### New configuration

| Variable | Service | Default | Meaning |
|----------|---------|---------|---------|
| `PARKINGSPOTTER_HISTORY_RETENTION_DAYS` | backend | `90` | Delete `spot_history` sessions that ended more than this many days ago. `0` keeps history forever. Invalid or negative values log a warning and use `90`. Values above `36500` (100 years) log a warning and are capped at `36500`, since larger ones overflow the cutoff date. |

### Out of scope

- Shrinking the database file (`VACUUM` / `auto_vacuum`). SQLite reuses freed
  pages, so the file stops growing once retention is steady; reclaiming disk is
  a manual `VACUUM` if ever needed.
- Retention for `spots` (one row per spot) and `spot_observations` (one row per
  spot and camera). Both are bounded by the number of spots.
- `PRAGMA synchronous` tuning. The default (`FULL`) stays; durability first.
- A long-lived shared connection or connection pool. Connections stay
  per-operation, now all opened through the helper. That is enough to fix
  locking (WAL + busy_timeout) without changing lifecycle or test fixtures.
- Exception handling inside the existing dwell checker and simulator loops
  (the "soon" lifecycle is Phase 3, `R0.3`).
- Any change to `POST /spots` HMAC, the projects API or the frontend.

## Decisions

- **Helper shape.** `db.connect()` is an async context manager wrapping
  `aiosqlite.connect(DB_PATH)`. It reads the module-level `DB_PATH` at call
  time, so existing tests that `monkeypatch.setattr(db, "DB_PATH", ...)` keep
  working.
- **busy_timeout per connection, WAL once per database.** `busy_timeout` is a
  connection setting, so it is applied on every open, before anything else.
  `journal_mode=WAL` is stored in the database file, so the helper sets it the
  first time it sees a given path and remembers the path for the life of the
  process. If SQLite cannot enable WAL (for example `:memory:` or a filesystem
  without shared-memory support), the helper logs one warning naming the mode it
  got and carries on.
- **busy_timeout is a constant (5000 ms), not an env var.** `todo.md` fixes the
  value, and nothing in the pilot calls for tuning it.
- **Retention removes whole sessions.** A row may be deleted only if every
  dwell session it belongs to ended before the cutoff. Concretely, per spot:
  find the latest `available` row recorded before the cutoff and delete that
  spot's rows recorded strictly before it. Consequences:
  - Completed sessions that ended before the cutoff disappear completely, so
    they can't leave a truncated session behind that would distort dwell stats.
  - A session that started before the cutoff but ended after it is kept in full.
  - A spot's current open session (an `occupied`/`soon` run with no closing
    `available`) is never touched, however old.
  - One `available` row per spot may stay older than the cutoff. It is a no-op
    for dwell parsing and keeps the rule simple and idempotent.
  - If a spot has no `available` row before the cutoff, nothing is deleted for
    that spot.
- **Pruning commits one spot at a time.** Each spot's delete is its own short
  write transaction, so even a first prune of a large database does not hold
  the write lock for long enough to starve detector ingest.
- **Retention is on by default, with `0` to disable.** Matches the `todo.md`
  default of 90 days. Read from the environment at call time so tests can
  `monkeypatch.setenv`.
- **Startup pass is awaited and failure-tolerant.** It runs in `lifespan` after
  `init_db()` and logs the number of rows removed. An exception is logged and
  the backend still starts; retention is housekeeping, not a reason to refuse
  to serve.
- **Daily loop survives errors.** The background task sleeps 24 hours, prunes,
  and logs and continues on any exception, so one bad night doesn't stop
  retention for good.
- **Timestamps.** The cutoff is compared as an ISO-8601 UTC string, the same
  lexicographic ordering the existing `ORDER BY recorded_at` queries rely on.
  At day granularity, sub-second format differences don't matter.
- **No new dependencies.**

## Context

- Guardrails (`AGENTS.md`): single-process backend (#9), so the "once per
  database" WAL memo and the retention task live in one process; no raw frames
  or plates stored (privacy posture unchanged; retention tightens it).
- Patterns to follow: `_spawn_background` in `main.py` for the loop, env
  parsing like `_env_truthy`, the `monkeypatch.setattr(db, "DB_PATH", ...)`
  fixtures in `backend/tests/`.
- Files likely to change: `backend/app/db.py`, `backend/app/main.py`, new
  `backend/tests/test_sqlite_wal_retention.py`, `README.md` (backend env table),
  `backend/README.md` (env table, Database section, backup note).
- WAL creates `parking.db-wal` and `parking.db-shm` next to the database.
  `.gitignore` already covers `*.db-wal` and `*.db-shm`. Backups must use
  `sqlite3 parking.db ".backup backup.db"` (or stop the backend) rather than
  copying only the `.db` file. WAL needs a local filesystem, which the Compose
  volume and the laptop demo both are.
