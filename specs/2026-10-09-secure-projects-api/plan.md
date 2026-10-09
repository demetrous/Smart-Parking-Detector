# Plan: Secure the projects API (Phase 1, `R0.1`)

Each group is independently committable. Run `python -m pytest` after each
backend group.

---

## Group 1: Config and token check

1. Add project-write settings, read from the environment at request time (so
   tests can `monkeypatch.setenv`): token, max upload MB, max ZIP entries, max
   ZIP uncompressed MB, with the defaults from `requirements.md`.
2. Add `check_projects_token(header_value) -> bool` using
   `hmac.compare_digest`; returns `True` when no token is configured.
3. Log one startup warning in `create_app()` when the token is unset.

## Group 2: Write-route middleware

4. Add a middleware that matches project write routes only
   (`POST /projects`, `PATCH /projects/{id}`, `POST /projects/{id}/assets`,
   `POST /projects/import`).
5. For those routes: missing or wrong bearer token → `401` JSON with
   `WWW-Authenticate: Bearer`; `Content-Length` above the upload cap → `413`.
   Both happen before the body is read.
6. Leave reads, `/spots`, `/ws` and every other route untouched.

## Group 3: Upload cap

7. In `save_project_asset`, stop at the cap while copying chunks: delete the
   partial file and raise `413`. Write the manifest only after a successful
   copy (already true; keep it).

## Group 4: ZIP import limits

8. Replace `await file.read()` with the spooled `file.file`, check its size
   against the upload cap (`413`).
9. Before extracting: entry count over limit → `413`; sum of
   `ZipInfo.file_size` over limit → `413`.
10. During extraction, stream each member and count bytes actually written;
    over the uncompressed limit → `413`. All failures go through the existing
    `rmtree` cleanup.
11. Keep the path-traversal checks and the `project.json` / id validation as is.

## Group 5: Frontend token wiring

12. In `frontend/src/lib/api.ts`, add a helper that returns
    `{ Authorization: 'Bearer …' }` when `import.meta.env.VITE_PROJECTS_TOKEN`
    is set, and merge it into `createProject`, `patchProject`,
    `uploadProjectAsset`, `importProject`.
13. Surface `401` and `413` as clear error messages (status-specific text in
    the thrown `Error`).
14. Add `VITE_PROJECTS_TOKEN` to `frontend/ENV_EXAMPLE.txt` with the "local
    authoring only, never in a public build" warning.

## Group 6: Tests

15. In `backend/tests/test_projects_api.py` (lower the caps via env in tests
    so payloads stay tiny):
    - token set: write without header → `401`; wrong token → `401`; correct
      token → `200`; reads without header → `200`
    - token unset: writes still work
    - oversized asset upload → `413`, no file left in the project dir, manifest
      unchanged
    - oversized `Content-Length` rejected before body read → `413`
    - ZIP with too many entries → `413`, no project dir left
    - ZIP over the uncompressed cap (small compressed, large expanded) →
      `413`, no project dir left
    - existing path-traversal and round-trip tests still pass

## Group 7: Docs and close-out

16. `README.md`: add the five env vars to the configuration reference; mark
    project writes as token-protected in the API table and add the missing
    `PATCH /projects/{id}` and `GET /projects/{id}` rows; one paragraph on the
    frontend-token caveat.
17. Tick Phase 1 items in `specs/roadmap.md` and `R0.1` Progress in `todo.md`.
