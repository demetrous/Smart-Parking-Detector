import type { Spot, SpotUpdateEvent } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

export async function fetchSpots(): Promise<Spot[]> {
  const res = await fetch(`${API_URL}/spots`);
  if (!res.ok) throw new Error(`Failed to fetch spots: ${res.status}`);
  return res.json();
}

export function connectWs(onEvent: (ev: SpotUpdateEvent) => void): WebSocket {
  const wsUrl = API_URL.replace(/^http/, 'ws') + '/ws';
  const ws = new WebSocket(wsUrl);
  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data) as SpotUpdateEvent;
      if (data?.type === 'spot.update') onEvent(data);
    } catch {}
  };
  return ws;
}


