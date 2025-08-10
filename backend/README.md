# Smart Parking Backend (FastAPI)

## Endpoints
- GET `/health` → `{ ok: true }`
- GET `/spots` → list of spots
- WS `/ws` → realtime spot.update events

## Run (local)
```
python -m venv .venv
.venv\Scripts\activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
```

CORS defaults allow `http://localhost:5173`. Configure via `CORS_ORIGINS` env var (comma-separated).
