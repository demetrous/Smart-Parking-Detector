# Smart Parking Detector (AI app)

Turn city cameras into a friendly assistant that helps drivers find open parking — or spots that are likely to be free soon.

## What’s here now
- A live map demo under `web-mock/` (Leaflet) with green/yellow/red spots and a simulation toggle
- Project description assets under `Description/` (images, PDF, PSD)
- Repo boilerplate: `.gitignore`, `LICENSE`, `.gitattributes`

## Quick start (UI mock)
1. Open `web-mock/index.html` in a browser
2. Click "Start Simulation" to see spots change (occupied → soon → available)
3. Click any marker → "Navigate" opens Google Maps to that location

## Concept
- **Green**: available
- **Yellow**: potentially available soon (e.g., car moving, door open)
- **Red**: occupied

## Architecture (MVP goal)
- Detection: YOLOv8
- Tracking: DeepSORT/ByteTrack
- Backend: FastAPI (REST + WebSocket)
- Frontend: React + Mapbox (or Leaflet)
- Storage: in-memory/Redis for current state, optional DB for history

Example diagrams and mock map pins are in `Description/`:

- `Description/img6.png` – map marker concept
- `Description/img7.png` – system architecture
- `Description/img8.png` – multi-camera flow
- `Description/img9.png` – storyboard

## Folder layout
```
Description/        # Images, PSD, and project PDF
web-mock/           # Lightweight map demo (no build needed)
  ├─ index.html
  ├─ app.js
  └─ style.css
```

## Roadmap (suggested milestones)
- Phase 1: Single-camera spot occupancy (fixed polygons)
- Phase 2: ID tracking + debounced state changes
- Phase 3: "Soon" predictions (rules first: door-open/motion → yellow)
- Phase 4: FastAPI backend + WebSocket updates
- Phase 5: React + Mapbox frontend
- Phase 6: Multi-camera calibration/merge
- Phase 7: GPU optimization, Docker, privacy masking

## License
MIT — see `LICENSE`.

## Contributing
PRs are welcome. Keep code readable and small, and prefer clear naming. If adding large assets, link to external storage.

---
Friendly note: this repo currently ships a zero-dependency UI mock so it’s easy to demo. We’ll swap in the real backend + model pipeline as we progress.
