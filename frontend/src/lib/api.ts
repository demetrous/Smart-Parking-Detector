import type { Spot, SpotUpdateEvent } from '../types';

const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000';

export const API_BASE_URL = API_URL;

// Local authoring only: Vite inlines VITE_* values into the JS bundle, so anyone
// who loads the page can read this token. Never set it for a publicly served build.
const PROJECTS_TOKEN = ((import.meta.env.VITE_PROJECTS_TOKEN as string | undefined) ?? '').trim();

function withProjectsAuth(headers: Record<string, string> = {}): Record<string, string> {
  return PROJECTS_TOKEN ? { ...headers, Authorization: `Bearer ${PROJECTS_TOKEN}` } : headers;
}

export class ProjectWriteError extends Error {
  readonly status: number;

  constructor(action: string, status: number) {
    super(`Failed to ${action}: ${status}`);
    this.name = 'ProjectWriteError';
    this.status = status;
  }

  /** Short, user-facing reason for the statuses the projects API guards with. */
  get reason(): string | null {
    if (this.status === 401) return 'projects token missing or wrong (VITE_PROJECTS_TOKEN)';
    if (this.status === 413) return 'too large for the backend size limit';
    return null;
  }
}

/** Appends the 401/413 reason to a status message, if the error carries one. */
export function describeProjectError(message: string, error: unknown): string {
  const reason = error instanceof ProjectWriteError ? error.reason : null;
  return reason ? `${message}: ${reason}` : message;
}

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
    headers: withProjectsAuth({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new ProjectWriteError('create project', res.status);
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
    headers: withProjectsAuth({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(patch),
  });
  if (!res.ok) throw new ProjectWriteError('update project', res.status);
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
    headers: withProjectsAuth(),
    body: formData,
  });
  if (!res.ok) throw new ProjectWriteError('upload project asset', res.status);
  return res.json();
}

export async function importProject(file: File): Promise<{ project: ProjectManifest; importedFiles: number }> {
  const formData = new FormData();
  formData.append('file', file, file.name);
  const res = await fetch(`${API_URL}/projects/import`, {
    method: 'POST',
    headers: withProjectsAuth(),
    body: formData,
  });
  if (!res.ok) throw new ProjectWriteError('import project', res.status);
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
