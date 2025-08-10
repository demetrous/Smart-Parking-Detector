import { Marker } from 'react-map-gl/mapbox';
import { useSpots } from '../state/SpotsProvider';

function colorFor(status: string) {
  if (status === 'available') return '#22c55e';
  if (status === 'soon') return '#f59e0b';
  return '#ef4444';
}

export default function MapMarkers() {
  const { spots } = useSpots();
  return (
    <>
      {spots.map((s) => (
        <Marker key={s.id} longitude={s.lng} latitude={s.lat} anchor="bottom">
          <span
            title={`Spot ${s.id}: ${s.status}`}
            style={{
              display: 'inline-block',
              width: 14,
              height: 14,
              borderRadius: 9999,
              background: colorFor(s.status),
              border: '2px solid white',
              boxShadow: '0 1px 6px rgba(0,0,0,0.35)'
            }}
          />
        </Marker>
      ))}
    </>
  );
}


