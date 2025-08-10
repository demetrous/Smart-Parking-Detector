import { Marker } from 'react-map-gl/mapbox';
import { useSpots } from '../state/SpotsProvider';

function colorFor(status: string) {
  if (status === 'available') return '#22c55e';
  if (status === 'soon') return '#f59e0b';
  return '#ef4444';
}

function pinDataUrl(color: string, size = 28) {
  // Simple, visible pin with white outline and inner dot
  const outline = '#ffffff';
  const stroke = '#111827';
  const r = Math.max(1, Math.round(size * 0.18));
  const cx = 12;
  const cy = 9;
  const svg = `
    <svg xmlns='http://www.w3.org/2000/svg' width='24' height='28' viewBox='0 0 24 28'>
      <defs>
        <filter id='shadow' x='-50%' y='-50%' width='200%' height='200%'>
          <feDropShadow dx='0' dy='1.5' stdDeviation='1.2' flood-color='rgba(0,0,0,0.35)'/>
        </filter>
      </defs>
      <path d='M12 1.5c-4.97 0-9 3.94-9 8.8 0 6.45 8.35 15.45 8.7 15.82.17.19.4.29.65.29s.48-.1.65-.29C12.65 25.75 21 16.75 21 10.3c0-4.86-4.03-8.8-9-8.8z'
            fill='${outline}' stroke='${stroke}' stroke-width='0.6' filter='url(#shadow)' />
      <path d='M12 2.5c-4.41 0-8 3.49-8 7.8 0 5.77 7.17 13.8 8 14.74.83-.94 8-8.97 8-14.74 0-4.31-3.59-7.8-8-7.8z' fill='${color}' />
      <circle cx='${cx}' cy='${cy}' r='${r+1}' fill='${outline}'/>
      <circle cx='${cx}' cy='${cy}' r='${r}' fill='${stroke}' fill-opacity='0.85'/>
    </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export default function MapMarkers() {
  const { spots } = useSpots();
  return (
    <>
      {spots.map((s) => (
        <Marker key={s.id} longitude={s.lng} latitude={s.lat} anchor="bottom">
          <img
            src={pinDataUrl(colorFor(s.status))}
            alt={`Spot ${s.id}: ${s.status}`}
            width={28}
            height={28}
            style={{ display: 'block' }}
          />
        </Marker>
      ))}
    </>
  );
}


