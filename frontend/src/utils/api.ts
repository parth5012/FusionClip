import {
  normalizeSettingsStatus,
  resolveTunnelStatus,
} from './tunnel';
import type { TunnelStatus } from './tunnel';

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export interface StorageItem {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  last_modified?: string;
  url?: string;
}

export interface ListResponse {
  current_dir: string;
  directories: StorageItem[];
  files: StorageItem[];
}

export interface UploadResponse {
  message: string;
  filename: string;
  path: string;
  url: string;
}

export interface TaskResponse {
  message: string;
  task_id: string;
  status: string;
}

export interface TaskStatusResponse {
  id: string;
  state: string;
  info: any;
}

export async function fetchFiles(prefix = ''): Promise<ListResponse> {
  const url = `${API_BASE_URL}/api/storage/list?prefix=${encodeURIComponent(prefix)}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to list files');
  }
  return res.json();
}

export async function uploadFile(file: File, folder = ''): Promise<UploadResponse> {
  const url = `${API_BASE_URL}/api/storage/upload?folder=${encodeURIComponent(folder)}`;
  const formData = new FormData();
  formData.append('file', file);
  
  const res = await fetch(url, {
    method: 'POST',
    body: formData,
  });
  
  if (!res.ok) {
    throw new Error('Failed to upload file');
  }
  return res.json();
}

export async function deleteFile(path: string): Promise<{ message: string }> {
  const url = `${API_BASE_URL}/api/storage/delete?path=${encodeURIComponent(path)}`;
  const res = await fetch(url, {
    method: 'DELETE',
  });
  
  if (!res.ok) {
    throw new Error('Failed to delete file');
  }
  return res.json();
}

export async function createFolder(folderPath: string): Promise<{ message: string; path: string }> {
  const url = `${API_BASE_URL}/api/storage/create-folder?folder_path=${encodeURIComponent(folderPath)}`;
  const res = await fetch(url, {
    method: 'POST',
  });
  
  if (!res.ok) {
    throw new Error('Failed to create folder');
  }
  return res.json();
}

export async function startTask(path: string, taskType = 'transcode'): Promise<TaskResponse> {
  const url = `${API_BASE_URL}/api/tasks/process?path=${encodeURIComponent(path)}&task_type=${encodeURIComponent(taskType)}`;
  const res = await fetch(url, {
    method: 'POST',
  });
  
  if (!res.ok) {
    throw new Error(`Failed to start task: ${taskType}`);
  }
  return res.json();
}

export async function getTaskStatus(taskId: string): Promise<TaskStatusResponse> {
  const url = `${API_BASE_URL}/api/tasks/status/${taskId}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch task status');
  }
  return res.json();
}

export interface MediaAsset {
  id: number;
  title: string;
  file_path: string;
  file_size: number;
  content_type: string;
  duration: number;
  url: string;
  created_at: string | null;
}

export async function fetchMediaCatalog(query = '', limit = 20): Promise<MediaAsset[]> {
  const url = query
    ? `${API_BASE_URL}/api/media/search?query=${encodeURIComponent(query)}&limit=${limit}`
    : `${API_BASE_URL}/api/media`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch media catalog');
  }
  return res.json();
}

/* ── Provider API keys ─────────────────────────────────────────────────────
 * Keys are submitted once in plaintext and stored encrypted server-side.
 * They are never readable again: the status endpoint returns only whether a
 * provider is configured plus the last four characters.
 * ------------------------------------------------------------------------ */

export type SecretProvider = 'gemini' | 'elevenlabs';

export interface ProviderSecretStatus {
  configured: boolean;
  last4: string | null;
}

export interface SecretStatusResponse {
  gemini: ProviderSecretStatus;
  elevenlabs: ProviderSecretStatus;
}

export interface SaveSecretsPayload {
  gemini_api_key?: string;
  elevenlabs_api_key?: string;
}

export interface SaveSecretsResponse {
  status: string;
  updated: SecretProvider[];
}

export interface DeleteSecretResponse {
  status: string;
  provider: string;
  deleted: boolean;
}

export async function fetchSecretStatus(): Promise<SecretStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/settings/secrets`);
  if (!res.ok) {
    throw new Error('Failed to fetch API key status');
  }
  return res.json();
}

export async function saveSecrets(payload: SaveSecretsPayload): Promise<SaveSecretsResponse> {
  const res = await fetch(`${API_BASE_URL}/api/settings/secrets`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    throw new Error('Failed to save API keys');
  }
  return res.json();
}

export async function deleteSecret(provider: SecretProvider): Promise<DeleteSecretResponse> {
  const res = await fetch(`${API_BASE_URL}/api/settings/secrets/${provider}`, {
    method: 'DELETE',
  });

  if (!res.ok) {
    throw new Error(`Failed to remove ${provider} API key`);
  }
  return res.json();
}

/* ── Colab Compute Metrics ─────────────────────────────────────────────── */

export interface ColabMetricsResponse {
  status: 'connected' | 'disconnected';
  metrics: {
    vram_used: number;
    vram_total: number;
    ram_used: number;
    ram_total: number;
    cpu_load: number;
    active_task: string | null;
    vram_percent: number;
    ram_percent: number;
    updated_at: number;
  } | null;
}

export async function fetchColabMetrics(): Promise<ColabMetricsResponse> {
  const res = await fetch(`${API_BASE_URL}/api/colab/metrics`);
  if (!res.ok) {
    throw new Error('Failed to fetch Colab metrics');
  }
  return res.json();
}

/* ── Colab Tunnel (backend-backed, #79) ──────────────────────────────────
 * The tunnel endpoint URL and connection intent live in the server-side
 * settings store (keys `colab_tunnel_url` / `colab_tunnel_status`) and are
 * written via POST /api/colab/tunnel. The *effective* status additionally
 * honours the GET /api/colab/metrics 10s-staleness rule: a tunnel whose
 * notebook stopped reporting is shown as disconnected even if the stored
 * intent is still "running". Nothing here reads localStorage.
 * ------------------------------------------------------------------------ */

export type { TunnelStatus };

export interface TunnelSettings {
  url: string;
  status: TunnelStatus;
}

export interface ColabTunnelState extends TunnelSettings {
  /** Raw liveness from GET /api/colab/metrics (fresh notebook report?). */
  metricsConnected: boolean;
}

/** Read the persisted tunnel URL + intent from GET /api/settings. */
export async function fetchTunnelSettings(): Promise<TunnelSettings> {
  const res = await fetch(`${API_BASE_URL}/api/settings`);
  if (!res.ok) {
    throw new Error('Failed to fetch tunnel settings');
  }
  const body = await res.json();
  return {
    url: typeof body?.colab_tunnel_url === 'string' ? body.colab_tunnel_url : '',
    status: normalizeSettingsStatus(body?.colab_tunnel_status),
  };
}

/** Persist the tunnel URL + intent via POST /api/colab/tunnel. */
export async function configureColabTunnel(
  url: string,
  status: TunnelStatus,
): Promise<TunnelSettings> {
  const res = await fetch(
    `${API_BASE_URL}/api/colab/tunnel?url=${encodeURIComponent(url)}&status=${encodeURIComponent(status)}`,
    { method: 'POST' },
  );
  if (!res.ok) {
    throw new Error('Failed to configure Colab tunnel');
  }
  const body = await res.json();
  return {
    url: typeof body?.colab_url === 'string' ? body.colab_url : url,
    status: normalizeSettingsStatus(body?.colab_status),
  };
}

/** Effective tunnel state: settings intent resolved against metrics liveness. */
export async function fetchColabTunnelState(): Promise<ColabTunnelState> {
  const [settings, metrics] = await Promise.all([
    fetchTunnelSettings(),
    fetchColabMetrics().catch(() => ({
      status: 'disconnected' as const,
      metrics: null,
    })),
  ]);
  const metricsConnected = metrics.status === 'connected';
  return {
    url: settings.url,
    status: resolveTunnelStatus(settings.status, metrics.status),
    metricsConnected,
  };
}

/* ── Generation API Endpoints ─────────────────────────────────────────── */

export interface GenerateTextResponse {
  status: string;
  output: string;
  colab?: boolean;
}

/**
 * Timestamped overlay for the waveform player. The backend emits one marker per
 * local-generation event it can attest to - today that is the voice-clone
 * provenance marker (kind: 'voice_clone'). Empty array means "nothing to show".
 */
export interface AudioMarker {
  time: number;
  label: string;
  kind: string;
}

export interface GenerateAudioResponse {
  status?: string;
  type?: string;
  filename?: string;
  url?: string;
  colab?: boolean;
  markers?: AudioMarker[];
  /** Present instead of `status` when the local pipeline refused honestly (#71). */
  degraded?: boolean;
  reason?: string;
  message?: string;
}

export interface GenerateImageResponse {
  status: string;
  parameters: { steps: number; scale: number };
  filename: string;
  url: string;
  colab?: boolean;
}

async function postGenerate<T>(url: string, fallbackMessage: string): Promise<T> {
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err?.detail;
    let message = fallbackMessage;
    if (typeof detail === 'string') {
      message = detail;
    } else if (detail) {
      message = JSON.stringify(detail);
    }
    throw new Error(message);
  }
  return res.json();
}

export async function generateText(prompt: string, model?: string): Promise<GenerateTextResponse> {
  const params = new URLSearchParams({ prompt });
  if (model) params.set('model', model);
  const url = `${API_BASE_URL}/api/generate/text?${params.toString()}`;
  return postGenerate<GenerateTextResponse>(url, 'Text generation failed');
}

export async function generateAudio(
  prompt: string,
  type: 'tts' | 'sfx' | 'voice_clone' = 'tts',
  voiceId?: string,
  duration?: number,
  reference?: string,
): Promise<GenerateAudioResponse> {
  const params = new URLSearchParams({ prompt, type });
  if (voiceId) params.set('voice_id', voiceId);
  if (duration !== undefined) params.set('duration', duration.toString());
  // Zero-shot cloning (XTTS v2): catalog asset file_path used as the speaker reference.
  if (reference) params.set('reference', reference);
  const url = `${API_BASE_URL}/api/generate/audio?${params.toString()}`;
  return postGenerate<GenerateAudioResponse>(url, 'Audio generation failed');
}

export async function generateImage(
  prompt: string,
  steps = 28,
  scale = 7.5,
  aspectRatio?: string,
  provider?: string,
): Promise<GenerateImageResponse> {
  const params = new URLSearchParams({
    prompt,
    steps: steps.toString(),
    scale: scale.toString(),
  });
  if (aspectRatio) params.set('aspect_ratio', aspectRatio);
  if (provider) params.set('provider', provider);
  const url = `${API_BASE_URL}/api/generate/image?${params.toString()}`;
  return postGenerate<GenerateImageResponse>(url, 'Image generation failed');
}

/** Dispatch handle returned by POST /api/generate/video (poll with getTaskStatus). */
export interface GenerateVideoResponse {
  task_id: string;
  status: string;
  type: string;
  source: string;
  num_frames: number;
  fps: number;
}

/** Final payload of a finished video job (Celery SUCCESS result). */
export interface VideoGenerationResult {
  status?: string;
  type?: string;
  filename?: string;
  url?: string;
  num_frames?: number;
  fps?: number;
  degraded?: boolean;
  reason?: string;
  message?: string;
}

/**
 * Start local SVD image-to-video. Returns immediately with a Celery task id;
 * frame-level progress is read through getTaskStatus() using the same
 * `info.percent` / `info.status` contract the file manager's job panel uses.
 */
export async function startVideoGeneration(
  source: string,
  numFrames: number,
  fps: number,
): Promise<GenerateVideoResponse> {
  const params = new URLSearchParams({
    source,
    num_frames: numFrames.toString(),
    fps: fps.toString(),
  });
  const url = `${API_BASE_URL}/api/generate/video?${params.toString()}`;
  return postGenerate<GenerateVideoResponse>(url, 'Video generation failed');
}

