# Validation: Secure the projects API (Phase 1, `R0.1`)

Ready to merge when everything below holds.

## Automated

- [ ] `python -m pytest` exits 0 from the repo root (no GPU, camera or weights)
- [ ] `cd frontend && npm run lint && npm run build` exits 0
- [ ] CI is green on the PR

### Required test coverage

- [ ] Token configured: unauthenticated write → `401` on all four write endpoints
- [ ] Token configured: wrong token → `401`; correct token → success
- [ ] Token configured: `GET /projects`, `GET /projects/{id}`, asset GET and export still work without a header
- [ ] Token unset: writes succeed (local dev path)
- [ ] Oversized asset upload → `413`; no partial file; manifest unchanged
- [ ] Oversized `Content-Length` → `413` without the body being processed
- [ ] ZIP over entry limit → `413`; no project directory left behind
- [ ] ZIP over uncompressed limit → `413`; no project directory left behind
- [ ] Existing path-traversal and export/import round-trip tests pass unchanged

## Manual

- [ ] Backend started without `PARKINGSPOTTER_PROJECTS_TOKEN` logs one clear warning
- [ ] With the token set on both sides, the hybrid view can create a project, upload media and import a ZIP
- [ ] With the token set only on the backend, the hybrid view shows a readable 401 error instead of failing silently

## Guardrail check

- [ ] `POST /spots` HMAC code and tests untouched
- [ ] Extension allowlist and path-traversal guards unchanged or stricter
- [ ] No new dependencies
- [ ] No feature changes in `HybridStreetMapView.tsx` / `SimulationView.tsx`

## Definition of done

All automated and manual checks pass, a separate review session has checked the
diff against this file, `README.md` and `frontend/ENV_EXAMPLE.txt` document the
new variables and the frontend-token caveat, and Phase 1 boxes are ticked in
`specs/roadmap.md` and `todo.md`.
