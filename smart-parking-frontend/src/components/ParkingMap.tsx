import { useTheme } from './ThemeProvider';
import Map, { ViewState } from 'react-map-gl';
import 'mapbox-gl/dist/mapbox-gl.css';

const styles = {
  light: 'mapbox://styles/mapbox/light-v11',
  dark: 'mapbox://styles/mapbox/dark-v11',
};

export default function ParkingMap() {
  const { theme } = useTheme();
  const token = import.meta.env.VITE_MAPBOX_TOKEN as string | undefined;

  return (
    <div className="h-dvh w-full">
      <Map
        mapboxAccessToken={token}
        reuseMaps
        initialViewState={{ longitude: -122.3519, latitude: 47.6223, zoom: 16 } as ViewState}
        mapStyle={styles[theme]}
        style={{ width: '100%', height: '100%' }}
      />
    </div>
  );
}


