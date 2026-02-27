import Map from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useTheme } from './ThemeProvider';
import MapMarkers from './MapMarkers';

const STYLE_LIGHT = 'https://api.maptiler.com/maps/dataviz/style.json';
const STYLE_DARK = 'https://api.maptiler.com/maps/dataviz-dark/style.json';

export default function ParkingMap() {
  const { theme } = useTheme();
  const token = import.meta.env.VITE_MAPTILER_KEY as string | undefined;

  if (!token) {
    return (
      <div className="h-dvh w-full grid place-items-center text-center px-6">
        <div className="max-w-md rounded-xl border border-slate-300 dark:border-slate-700 p-5 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <h2 className="font-semibold mb-2">MapTiler key missing</h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Create a <code>.env</code> file in <code>frontend/</code> with
            <br />
            <code>VITE_MAPTILER_KEY=your_key_here</code>
            <br />
            then restart the dev server. Get a free key at{' '}
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
