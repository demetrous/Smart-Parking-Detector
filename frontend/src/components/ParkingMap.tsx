import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useTheme } from './ThemeProvider';
import MapMarkers from './MapMarkers';

const STYLE_LIGHT = 'https://api.maptiler.com/maps/dataviz/style.json';
const STYLE_DARK = 'https://api.maptiler.com/maps/dataviz-dark/style.json';

/** Values copied from ENV_EXAMPLE without editing — MapTiler returns 403 and the basemap stays blank. */
const PLACEHOLDER_MAPTILER_KEYS = new Set(
  ['', 'your_maptiler_key_here', 'your_key_here', 'changeme', 'replace_me'].map((s) => s.toLowerCase()),
);

function isUsableMaptilerKey(key: string | undefined): boolean {
  const t = (key ?? '').trim();
  if (!t) return false;
  return !PLACEHOLDER_MAPTILER_KEYS.has(t.toLowerCase());
}

export default function ParkingMap() {
  const { theme } = useTheme();
  const token = import.meta.env.VITE_MAPTILER_KEY as string | undefined;

  if (!isUsableMaptilerKey(token)) {
    return (
      <div className="h-dvh w-full grid place-items-center text-center px-6">
        <div className="max-w-md rounded-xl border border-slate-300 dark:border-slate-700 p-5 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <h2 className="font-semibold mb-2">MapTiler key missing or still a placeholder</h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Create or edit <code>.env</code> in <code>frontend/</code> and set a real key (not the example text):
            <br />
            <code>VITE_MAPTILER_KEY=…</code>
            <br />
            Then restart the dev server. Free key at{' '}
            <a href="https://maptiler.com" target="_blank" rel="noreferrer" className="underline">
              maptiler.com
            </a>
            .
          </p>
        </div>
      </div>
    );
  }

  const styleUrl = `${theme === 'dark' ? STYLE_DARK : STYLE_LIGHT}?key=${token}`;

  return (
    <div className="h-dvh w-full">
      <Map
        reuseMaps
        initialViewState={{ longitude: -122.3519, latitude: 47.6223, zoom: 16 }}
        mapStyle={styleUrl}
        style={{ width: '100%', height: '100%' }}
      >
        <MapMarkers />
      </Map>
    </div>
  );
}
