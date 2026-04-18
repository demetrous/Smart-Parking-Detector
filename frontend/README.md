# ParkingSpotter — Frontend

React + TypeScript single-page app that renders a live parking map using MapLibre GL and MapTiler tiles. Spot status updates arrive over WebSocket from the backend and animate in real time.

## Stack

- **React 19** + **TypeScript** + **Vite 7**
- **MapLibre GL** + **react-map-gl v8** — map rendering (open-source, no proprietary lock-in)
- **MapTiler** — vector tile provider (free tier: 100 k map loads/month)
- **Tailwind CSS v4** — utility styling
- **Headless UI** + **Heroicons** — accessible UI primitives

## Setup

### MapTiler key

1. Sign up at [maptiler.com](https://maptiler.com) — free, no credit card needed.
2. Copy `ENV_EXAMPLE.txt` to `.env`:
   ```bash
   cp ENV_EXAMPLE.txt .env
   # or on Windows:  Copy-Item ENV_EXAMPLE.txt .env
   ```
3. Replace `your_maptiler_key_here` with your key.

### Run — standard local filesystem

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### Run — Google Drive / cloud-synced folder (Windows)

`npm install` fails on cloud drives because the virtual filesystem driver doesn't support the parallel writes npm uses. Use the provided PowerShell launcher instead — it installs packages once to `%LOCALAPPDATA%\ParkingSpotter\frontend\node_modules` and starts Vite from there automatically.

```powershell
cd frontend
.\dev.ps1          # installs on first run (~20 s), then starts immediately
```

The `.gdriveignore` file at the repo root also excludes `node_modules/` and other build artefacts from being synced to the cloud.

The app connects to the backend at `VITE_API_URL` (default `http://127.0.0.1:8000`).
If the backend is not running, the map still loads with an empty spot list.

## Build

```bash
npm run build   # Output in dist/
npm run preview # Preview the production build locally
```

### Troubleshooting: `Failed to resolve import "maplibre-gl/dist/maplibre-gl.css"`

That means `maplibre-gl` was not fully installed (the package should contain a `dist/` folder). Fix:

```bash
cd frontend
rm -rf node_modules && npm install
```

On Windows (PowerShell): `Remove-Item -Recurse -Force node_modules` then `npm install`.

If you use **`dev.ps1`** (cloud-drive layout), delete `%LOCALAPPDATA%\ParkingSpotter\frontend\node_modules` and run `dev.ps1` again — the script also auto-runs `npm install` when `maplibre-gl` is incomplete.

## Docker

```bash
docker compose up frontend
```

The frontend container serves the built static app on `http://localhost:5173`.
`VITE_API_URL` and `VITE_MAPTILER_KEY` are build-time values in the Docker image, so change them before rebuilding the frontend image.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_MAPTILER_KEY` | — | MapTiler API key (required) |
| `VITE_API_URL` | `http://127.0.0.1:8000` | Backend base URL |

## Source layout

```
src/
├── components/
│   ├── ParkingMap.tsx    # MapLibre map; switches style URL for light/dark
│   ├── MapMarkers.tsx    # SVG pin markers + popup (spot name, status, Navigate)
│   └── ThemeProvider.tsx # Light/dark context; persists to localStorage
├── state/
│   └── SpotsProvider.tsx # Fetches initial spots + subscribes to WS updates
├── lib/
│   └── api.ts            # fetchSpots() and connectWs() helpers
├── types.ts              # Spot, SpotUpdateEvent TypeScript types
├── App.tsx               # Layout shell + toolbar + legend
└── main.tsx              # React root
```

## Map themes

| Theme | MapTiler style |
|-------|---------------|
| Light | `dataviz` |
| Dark | `dataviz-dark` |

Toggle with the sun/moon button in the top-left corner. The preference is saved to `localStorage`.
