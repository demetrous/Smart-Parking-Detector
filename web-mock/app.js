/*
  Smart Parking – lightweight front-end mock with Leaflet
  - Shows demo markers (green/yellow/red)
  - Simulates live updates
  - Provides Navigate links via Google Maps
*/

// Seattle Center area as a nice neutral demo location
const INITIAL_CENTER = [47.6223, -122.3519];
const INITIAL_ZOOM = 16;

const Status = Object.freeze({
  AVAILABLE: 'available', // green
  POTENTIAL: 'potential', // yellow
  OCCUPIED: 'occupied',   // red
});

const statusToColor = {
  [Status.AVAILABLE]: '#22c55e',
  [Status.POTENTIAL]: '#f59e0b',
  [Status.OCCUPIED]: '#ef4444',
};

let map;
let markers = new Map(); // id -> marker
let simulateTimer = null;

// Demo dataset: five spots with deterministic positions
let spots = [
  { id: 'A1', lat: 47.62319, lng: -122.3546, status: Status.AVAILABLE },
  { id: 'A2', lat: 47.62270, lng: -122.3539, status: Status.POTENTIAL },
  { id: 'B1', lat: 47.62190, lng: -122.3527, status: Status.OCCUPIED },
  { id: 'B2', lat: 47.62230, lng: -122.3506, status: Status.AVAILABLE },
  { id: 'C1', lat: 47.62160, lng: -122.3515, status: Status.OCCUPIED },
];

function initMap() {
  map = L.map('map', {
    zoomControl: true,
    attributionControl: true,
  }).setView(INITIAL_CENTER, INITIAL_ZOOM);

  // Use a free, no-key tile style (Carto light) – replace later with Mapbox if desired
  L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap &copy; CARTO',
  }).addTo(map);

  renderSpots();
}

function makeIcon(color) {
  const svg = encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 2C8 2 5 5 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-4-3-7-7-7z" fill="rgba(0,0,0,0.15)"/>
      <circle cx="12" cy="9" r="2.7" fill="${color}" />
    </svg>`
  );
  return L.icon({
    iconUrl: `data:image/svg+xml,${svg}`,
    iconSize: [28, 28],
    iconAnchor: [14, 26],
    popupAnchor: [0, -24],
  });
}

function renderSpots() {
  // Remove old markers
  markers.forEach(m => m.remove());
  markers.clear();

  for (const spot of spots) {
    const icon = makeIcon(statusToColor[spot.status]);
    const marker = L.marker([spot.lat, spot.lng], { icon }).addTo(map);
    marker.bindPopup(buildPopupHtml(spot));
    marker.on('click', () => marker.setPopupContent(buildPopupHtml(spot)));
    markers.set(spot.id, marker);
  }
}

function buildPopupHtml(spot) {
  const label = spotLabel(spot.status);
  const gmaps = `https://www.google.com/maps/dir/?api=1&destination=${spot.lat},${spot.lng}`;
  return `
    <div style="min-width:180px">
      <div style="font-weight:700;margin-bottom:4px">Spot ${spot.id}</div>
      <div style="margin-bottom:8px">Status: <span style="color:${statusToColor[spot.status]}">${label}</span></div>
      <a href="${gmaps}" target="_blank" rel="noreferrer">Navigate</a>
    </div>
  `;
}

function spotLabel(status) {
  switch (status) {
    case Status.AVAILABLE: return 'Available';
    case Status.POTENTIAL: return 'Potentially soon';
    default: return 'Occupied';
  }
}

function updateSpot(id, newStatus) {
  const spot = spots.find(s => s.id === id);
  if (!spot) return;
  spot.status = newStatus;
  const marker = markers.get(id);
  if (marker) {
    marker.setIcon(makeIcon(statusToColor[newStatus]));
    marker.setPopupContent(buildPopupHtml(spot));
  }
}

function randomStep() {
  // Simple random walk through statuses to simulate changes
  const target = spots[Math.floor(Math.random() * spots.length)];
  const order = [Status.OCCUPIED, Status.POTENTIAL, Status.AVAILABLE];
  const idx = order.indexOf(target.status);
  const next = order[(idx + 1) % order.length];
  updateSpot(target.id, next);
}

function startSimulation() {
  if (simulateTimer) return;
  simulateTimer = setInterval(randomStep, 1600);
  document.getElementById('simulateBtn').innerText = 'Stop Simulation';
}

function stopSimulation() {
  if (!simulateTimer) return;
  clearInterval(simulateTimer);
  simulateTimer = null;
  document.getElementById('simulateBtn').innerText = 'Start Simulation';
}

function resetDemo() {
  stopSimulation();
  spots = [
    { id: 'A1', lat: 47.62319, lng: -122.3546, status: Status.AVAILABLE },
    { id: 'A2', lat: 47.62270, lng: -122.3539, status: Status.POTENTIAL },
    { id: 'B1', lat: 47.62190, lng: -122.3527, status: Status.OCCUPIED },
    { id: 'B2', lat: 47.62230, lng: -122.3506, status: Status.AVAILABLE },
    { id: 'C1', lat: 47.62160, lng: -122.3515, status: Status.OCCUPIED },
  ];
  renderSpots();
}

// Wire up UI
window.addEventListener('DOMContentLoaded', () => {
  initMap();
  document.getElementById('simulateBtn').addEventListener('click', () => {
    if (simulateTimer) stopSimulation(); else startSimulation();
  });
  document.getElementById('resetBtn').addEventListener('click', resetDemo);
});


