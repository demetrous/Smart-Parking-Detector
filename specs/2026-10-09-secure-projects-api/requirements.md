# Requirements: Secure the projects API (Phase 1, `R0.1`)

Source: `todo.md` § `R0.1` Secure the projects API. Roadmap: `specs/roadmap.md` Phase 1.

## Scope

Close the unauthenticated, uncapped write surface of the portable projects API
before it reaches any shared environment.

### In scope

| Endpoint | Change |
|----------|--------|
| `POST /projects` | Bearer token required when configured |
| `PATCH /projects/{id}` | Bearer token required when configured |
| `POST /projects/{id}/assets` | Bearer token required when configured; upload size cap |
| `POST /projects/import` | Bearer token required when configured; ZIP file size cap; entry-count and uncompressed-size limits |

Reads stay open: `GET /projects`, `GET /projects/{id}`,
`GET /projects/{id}/assets/...`, `GET /projects/{id}/export`.

### New configuration

| Variable | Service | Default | Meaning |
|----------|---------|---------|---------|
| `PARKINGSPOTTER_PROJECTS_TOKEN` | backend | unset | When set, project writes need `Authorization: Bearer <token>`; otherwise `401` |
| `PARKINGSPOTTER_MAX_UPLOAD_MB` | backend | `512` | Max size of one asset upload and of one import ZIP file |
| `PARKINGSPOTTER_MAX_ZIP_ENTRIES` | backend | `2000` | Max members in an import ZIP |
| `PARKINGSPOTTER_MAX_ZIP_UNCOMPRESSED_MB` | backend | `1024` | Max total uncompressed size of an import ZIP |
| `VITE_PROJECTS_TOKEN` | frontend | unset | Sent as the bearer token on project writes when set |

### Out of scope

- OpenCV `<5` pin: done in PR #1 (merged).
- Auth on read endpoints, users/roles, token rotation.
- Any change to `POST /spots` HMAC.
- New hybrid-view features (demo freeze); the only frontend change is the
  auth header.

## Decisions

- **Token unset = open writes plus a startup warning.** Keeps local dev
  friction-free, as `todo.md` specifies. The warning names the env var.
- **Constant-time compare** (`hmac.compare_digest`) for the token, matching
  the `POST /spots` pattern.
- **Reject before reading the body.** FastAPI/Starlette parse multipart bodies
  (spooling uploads to disk) before route dependencies run, so the token check
  and a `Content-Length` pre-check run in a small middleware scoped to project
  write routes. Unauthenticated or obviously oversized requests never get
  spooled.
- **Count bytes while copying as well.** `Content-Length` can be absent or
  wrong, so `save_project_asset` and `import_project_zip` also enforce the cap
  while reading and return `413` the moment it is exceeded.
- **ZIP limits are checked from the central directory before extraction:**
  entry count and the sum of `ZipInfo.file_size`. Extraction also counts
  actual bytes written, so a ZIP that lies about sizes still stops at the cap.
- **No partial state on rejection.** A rejected upload deletes its partly
  written file and leaves the manifest untouched; a rejected import removes the
  project directory (the existing `shutil.rmtree` cleanup path).
- **Import ZIP file cap reuses `PARKINGSPOTTER_MAX_UPLOAD_MB`** (512 MB).
  Import currently reads the whole upload into memory (`project_store.py:206`);
  it switches to the spooled file object so the cap is enforced without
  holding it all in RAM.
- **Frontend token is a local-authoring convenience only.** Vite inlines
  `VITE_*` values into the JS bundle, so the token is readable by anyone who
  loads the page. Docs must say a publicly served frontend must not set it.
- **No new dependencies.**

### Decisions made during implementation

- **The guard covers every mutating method under `/projects`** (`POST`,
  `PUT`, `PATCH`, `DELETE` on `/projects` and `/projects/...`), not a list of
  four routes, so a future write route is protected by default and trailing
  slash variants can't slip past. `OPTIONS` (CORS preflight) and reads pass.
- **JSON writes (create, patch) are capped at 1 MB.** They carry a small
  manifest; assets travel as uploads. Multipart requests get the upload cap
  plus 1 MB for multipart framing, so a file of exactly the cap still fits.
- **Bodies without `Content-Length` are counted as they stream** and stopped
  with `413` the moment they cross the limit.
- **`HybridStreetMapView.tsx` gets error-text changes only:** its four project
  write `catch` blocks now append the 401/413 reason ("projects token missing
  or wrong", "too large for the backend size limit") so the manual 401 check
  in `validation.md` is observable. No behaviour or feature change.

## Context

- Guardrails (`AGENTS.md`): every write endpoint ships with auth and size
  limits (#11); single-process backend (#9); demo freeze (#6) allows this
  header change as a security fix; uploads keep the extension allowlist and
  path-traversal guards.
- Patterns to follow: `backend/app/auth.py` (env-driven secret,
  constant-time compare), existing `HTTPException` style in
  `backend/app/project_store.py`, the `client` fixture in
  `backend/tests/test_projects_api.py`.
- Files likely to change: `backend/app/main.py`, `backend/app/project_store.py`,
  a new `backend/app/projects_auth.py` (or additions to `auth.py`),
  `backend/tests/test_projects_api.py`, `frontend/src/lib/api.ts`,
  `frontend/ENV_EXAMPLE.txt`, `README.md` (config table and API table, which
  also lacks `PATCH` and `GET /projects/{id}` today), `backend/README.md` if it
  documents env vars.
- `HybridStreetMapView.tsx`: error-message text only (see the decision above).
