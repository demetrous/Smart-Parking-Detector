import { useEffect, useRef } from 'react';
import { useTheme } from './ThemeProvider';
import Map from 'react-map-gl/mapbox';
import type mapboxgl from 'mapbox-gl';
import 'mapbox-gl/dist/mapbox-gl.css';

// Use one style (standard) and flip its light preset via setConfigProperty.
const STANDARD_STYLE = 'mapbox://styles/mapbox/standard';

export default function ParkingMap() {
  const { theme } = useTheme();
  const token = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined;

  if (!token) {
    return (
      <div className="h-dvh w-full grid place-items-center text-center px-6">
        <div className="max-w-md rounded-xl border border-slate-300 dark:border-slate-700 p-5 bg-white/80 dark:bg-slate-900/80 backdrop-blur">
          <h2 className="font-semibold mb-2">Mapbox token missing</h2>
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Create a <code>.env</code> file in <code>smart-parking-frontend/</code> with
            <br />
            <code>VITE_MAPBOX_TOKEN=your_mapbox_access_token_here</code>
            <br />
            then restart the dev server.
          </p>
        </div>
      </div>
    );
  }

  const mapRef = useRef<mapboxgl.Map | null>(null);

  // Apply light/dark without swapping the entire style (avoids sprite diff warning)
  const applyPreset = () => {
    try {
      const preset = theme === 'dark' ? 'night' : 'day';
      (mapRef.current as any)?.setConfigProperty?.('basemap', 'lightPreset', preset);
    } catch {
      // no-op: older styles may not support style components
    }
  };

  useEffect(() => {
    applyPreset();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);

  return (
    <div className="h-dvh w-full">
      <Map
        mapboxAccessToken={token}
        reuseMaps
        initialViewState={{ longitude: -122.3519, latitude: 47.6223, zoom: 16 }}
        mapStyle={STANDARD_STYLE}
        style={{ width: '100%', height: '100%' }}
        onLoad={(e) => {
          mapRef.current = e.target as unknown as mapboxgl.Map;
          applyPreset();
        }}
      />
    </div>
  );
}


