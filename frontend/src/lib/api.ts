import type { Spot, SpotUpdateEvent } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

export async function fetchSpots(): Promise<Spot[]> {
  const res = await fetch(`${API_URL}/spots`);
  if (!res.ok) throw new Error(`Failed to fetch spots: ${res.status}`);
  return res.json();
}

export type WsStatus = 'connected' | 'disconnected';

export interface WsController {
  close(): void;
}

const WS_BASE_DELAY_MS = 1_000;
const WS_MAX_DELAY_MS = 30_000;

/**
 * Opens a WebSocket to the backend and reconnects automatically on disconnect
 * using exponential back-off (1 s → 2 s → 4 s … capped at 30 s).
 * The back-off counter resets on each successful open.
 */
export function connectWs(
  onEvent: (ev: SpotUpdateEvent) => void,
  onStatus?: (status: WsStatus) => void,
): WsController {
  const wsUrl = API_URL.replace(/^http/, 'ws') + '/ws';
  let ws: WebSocket | null = null;
  let stopped = false;
  let attempt = 0;
  let retryTimer: ReturnType<typeof setTimeout> | null = null;

  function connect() {
    if (stopped) return;
    ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      attempt = 0;
      onStatus?.('connected');
    };

    ws.onmessage = (msg) => {
      try {
        const data = JSON.parse(msg.data) as SpotUpdateEvent;
        if (data?.type === 'spot.update') onEvent(data);
      } catch {
        // ignore malformed frames
      }
    };

    ws.onclose = () => {
      if (stopped) return;
      onStatus?.('disconnected');
      const delay = Math.min(WS_BASE_DELAY_MS * 2 ** attempt, WS_MAX_DELAY_MS);
      attempt++;
      retryTimer = setTimeout(connect, delay);
    };

    // onerror always precedes onclose — let onclose drive the reconnect
    ws.onerror = () => {};
  }

  connect();

  return {
    close() {
      stopped = true;
      if (retryTimer !== null) clearTimeout(retryTimer);
      ws?.close();
    },
  };
}
