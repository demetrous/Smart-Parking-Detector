import type { Spot, SpotUpdateEvent } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

export const API_BASE_URL = API_URL;

export async function fetchSpots(): Promise<Spot[]> {
  const res = await fetch(`${API_URL}/spots`);
  if (!res.ok) throw new Error(`Failed to fetch spots: ${res.status}`);
  return res.json();
}

export type ProjectMediaType = 'image' | 'video' | 'synthetic';

export type ProjectManifest = {
  schemaVersion: number;
  id: string;
  name: string;
  createdAt: string;
  updatedAt: string;
  media?: {
    type: ProjectMediaType;
    assetPath?: string | null;
    originalName?: string | null;
    contentType?: string | null;
  } | null;
  calibrationPath?: string | null;
  lastDetectionsPath?: string | null;
  geometryLinesPath?: string | null;
  uiState: {
    topPanePercent: number;
    selectedMode: ProjectMediaType;
  };
};

export type ProjectAsset = {
  path: string;
  url: string;
  originalName: string;
  contentType?: string | null;
  size: number;
};

export async function fetchProjects(): Promise<ProjectManifest[]> {
  const res = await fetch(`${API_URL}/projects`);
  if (!res.ok) throw new Error(`Failed to fetch projects: ${res.status}`);
  return (await res.json()).projects;
}

export async function createProject(name: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_URL}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error(`Failed to create project: ${res.status}`);
  return res.json();
}

export async function fetchProject(projectId: string): Promise<ProjectManifest> {
  const res = await fetch(`${API_URL}/projects/${projectId}`);
  if (!res.ok) throw new Error(`Failed to fetch project: ${res.status}`);
  return res.json();
}

export async function patchProject(projectId: string, patch: Partial<ProjectManifest>): Promise<ProjectManifest> {
  const res = await fetch(`${API_URL}/projects/${projectId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new Error(`Failed to update project: ${res.status}`);
  return res.json();
}

export async function uploadProjectAsset(
  projectId: string,
  kind: 'media' | 'calibration' | 'detections' | 'geometry' | 'asset',
  file: Blob,
  filename: string,
): Promise<ProjectAsset> {
  const formData = new FormData();
  formData.append('file', file, filename);
  const res = await fetch(`${API_URL}/projects/${projectId}/assets?kind=${kind}`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error(`Failed to upload project asset: ${res.status}`);
  return res.json();
}

export async function importProject(file: File): Promise<{ project: ProjectManifest; importedFiles: number }> {
  const formData = new FormData();
  formData.append('file', file, file.name);
  const res = await fetch(`${API_URL}/projects/import`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error(`Failed to import project: ${res.status}`);
  return res.json();
}

export function projectAssetUrl(projectId: string, assetPath: string): string {
  return `${API_URL}/projects/${projectId}/assets/${assetPath}`;
}

export function projectExportUrl(projectId: string): string {
  return `${API_URL}/projects/${projectId}/export`;
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
