# Validation: Secure the projects API (Phase 1, `R0.1`)

Ready to merge when everything below holds.

## Automated

- [x] `python -m pytest` exits 0 from the repo root (no GPU, camera or weights)
- [x] `cd frontend && npm run lint && npm run build` exits 0
- [x] CI is green on the PR

### Required test coverage

- [x] Token configured: unauthenticated write → `401` on all four write endpoints
- [x] Token configured: wrong token → `401`; correct token → success
- [x] Token configured: `GET /projects`, `GET /projects/{id}`, asset GET and export still work without a header
- [x] Token unset: writes succeed (local dev path)
- [x] Oversized asset upload → `413`; no partial file; manifest unchanged
- [x] Oversized `Content-Length` → `413` without the body being processed
- [x] ZIP over entry limit → `413`; no project directory left behind
- [x] ZIP over uncompressed limit → `413`; no project directory left behind
- [x] Existing path-traversal and export/import round-trip tests pass unchanged

## Manual

- [x] Backend started without `PARKINGSPOTTER_PROJECTS_TOKEN` logs one clear warning
- [x] With the token set on both sides, the hybrid view can create a project, upload media and import a ZIP
- [x] With the token set only on the backend, the hybrid view shows a readable 401 error instead of failing silently

## Guardrail check

- [x] `POST /spots` HMAC code and tests untouched
- [x] Extension allowlist and path-traversal guards unchanged or stricter
- [x] No new dependencies
- [x] No feature changes in `HybridStreetMapView.tsx` / `SimulationView.tsx`

## Definition of done

All automated and manual checks pass, a separate review session has checked the
diff against this file, `README.md` and `frontend/ENV_EXAMPLE.txt` document the
new variables and the frontend-token caveat, and Phase 1 boxes are ticked in
`specs/roadmap.md` and `todo.md`.

## Verification record (2026-10-09)

- Automated: CI green on PR #2 (backend tests, frontend lint/build); `python -m pytest` on master after Phase 2: 73 passed.
- Post-merge review: "Phase 1 verification review" thread (Opus 5.5, fresh session; rule 3 waived by the owner for this review). Its fixes landed in PR #3.
- Manual checks, run in headless Chromium against `uvicorn` + `vite` on master `a1346d8`:
  - No token: the backend logged exactly one line at startup, "PARKINGSPOTTER_PROJECTS_TOKEN is not set: project write endpoints are open. Set it before exposing this backend beyond localhost."
  - Token on both sides: New project → "Created Token Test 2"; Upload video → "Saved clip.mp4"; Import ZIP → "Imported Imported Check 2". All three requests carried `Authorization` and returned 200.
  - Token only on the backend: New project → "Could not create project: projects token missing or wrong (VITE_PROJECTS_TOKEN)", with the backend logging `401 Unauthorized`.
