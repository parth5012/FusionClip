import {
  normalizeSettingsStatus,
  resolveTunnelStatus,
} from './tunnel';
import type { TunnelStatus } from './tunnel';
import { buildMediaCatalogUrl } from './tags';

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

export interface TaskListItem {
  id: number;
  task_id: string;
  name: string;
  status: string;
  progress: number;
  error: string | null;
  logs?: string | null;
  traceback?: string | null;
  event_count?: number;
  error_type: string | null;
  retry_count: number;
  max_retries: number;
  last_retry_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskLogsResponse {
  task_id: string;
  logs: string | null;
  traceback: string | null;
  event_count: number;
}

export interface TaskListResponse {
  total: number;
  page: number;
  page_size: number;
  tasks: TaskListItem[];
}

export interface RetryResponse {
  message: string;
  original_task_id: string;
  new_task_id: string;
  retry_count: number;
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

export interface UpscaleParams {
  denoise?: number; // Denoising Strength (Creativity)
  controlnet_weight?: number; // ControlNet Weight (Resemblance)
  hdr?: number; // HDR post-pass strength
  fractality?: number; // Fractality noise + guidance bump
  prompt?: string; // optional img2img positive prompt
  temporal_strength?: number; // video_upscale: motion-aware temporal blend 0..1 (0 = off)
}

export async function startTask(
  path: string,
  taskType = 'transcode',
  upscaleParams?: UpscaleParams
): Promise<TaskResponse> {
  let url = `${API_BASE_URL}/api/tasks/process?path=${encodeURIComponent(path)}&task_type=${encodeURIComponent(taskType)}`;
  if (upscaleParams) {
    if (upscaleParams.denoise !== undefined) url += `&denoise=${encodeURIComponent(upscaleParams.denoise)}`;
    if (upscaleParams.controlnet_weight !== undefined) url += `&controlnet_weight=${encodeURIComponent(upscaleParams.controlnet_weight)}`;
    if (upscaleParams.hdr !== undefined) url += `&hdr=${encodeURIComponent(upscaleParams.hdr)}`;
    if (upscaleParams.fractality !== undefined) url += `&fractality=${encodeURIComponent(upscaleParams.fractality)}`;
    if (upscaleParams.prompt) url += `&prompt=${encodeURIComponent(upscaleParams.prompt)}`;
    if (upscaleParams.temporal_strength !== undefined) url += `&temporal_strength=${encodeURIComponent(upscaleParams.temporal_strength)}`;
  }
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

export interface UpscaledAsset {
  id: number;
  title: string;
  file_path: string;
  url: string;
}


export async function fetchTasks(
  page = 1,
  pageSize = 25,
  status?: string,
  taskType?: string,
  search?: string,
  errorType?: string,
): Promise<TaskListResponse> {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('page_size', String(pageSize));
  if (status) params.set('status', status);
  if (taskType) params.set('task_type', taskType);
  if (search) params.set('search', search);
  if (errorType) params.set('error_type', errorType);
  const url = `${API_BASE_URL}/api/tasks/list?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch tasks');
  }
  return res.json();
}

export interface TaskCountsResponse {
  running: number;
  pending: number;
  failed: number;
  completed: number;
}

export async function fetchTaskCounts(): Promise<TaskCountsResponse> {
  const url = `${API_BASE_URL}/api/tasks/counts`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch task counts');
  }
  return res.json();
}

export async function fetchTaskLogs(taskId: string): Promise<TaskLogsResponse> {
  const url = `${API_BASE_URL}/api/tasks/${encodeURIComponent(taskId)}/logs`;
  const res = await fetch(url);
  if (!res.ok) {
    if (res.status === 404) {
      return { task_id: taskId, logs: null, traceback: null, event_count: 0 };
    }
    throw new Error(`Failed to fetch task logs: ${res.statusText}`);
  }
  return res.json();
}

export async function retryTask(taskId: string): Promise<RetryResponse> {
  const url = `${API_BASE_URL}/api/tasks/${taskId}/retry`;
  const res = await fetch(url, {
    method: 'POST',
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || 'Failed to retry task');
  }
  return res.json();
}

export async function getErrorTypes(): Promise<string[]> {
  const url = `${API_BASE_URL}/api/tasks/errors/types`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch error types');
  }
  const data = await res.json();
  return data.error_types;
}



export interface TagItem {
  id: number;
  name: string;
}

export interface MediaAsset {
  id: number;
  title: string;
  file_path: string;
  file_size: number;
  content_type: string;
  duration: number;
  url: string;
  // Before/after comparison support (#58): the original this asset was
  // derived from, plus any upscaled outputs derived from this asset.
  source_path: string | null;
  source_url: string | null;
  upscaled_assets: UpscaledAsset[];
  tags?: TagItem[];
  created_at: string | null;
}

export async function fetchMediaCatalog(
  query = '',
  limit = 20,
  tags: string[] = []
): Promise<MediaAsset[]> {
  const url = buildMediaCatalogUrl(API_BASE_URL, query, limit, tags);
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch media catalog');
  }
  return res.json();
}

/* ── Tags API Endpoints (#105) ─────────────────────────────────────────── */

export async function fetchTags(): Promise<TagItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/tags`);
  if (!res.ok) {
    throw new Error('Failed to fetch tags');
  }
  return res.json();
}

export async function createTag(name: string): Promise<TagItem> {
  const res = await fetch(`${API_BASE_URL}/api/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to create tag');
  }
  return res.json();
}

export async function deleteTag(tagId: number): Promise<{ message: string; id: number }> {
  const res = await fetch(`${API_BASE_URL}/api/tags/${tagId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to delete tag');
  }
  return res.json();
}

export async function fetchAssetTags(assetId: number): Promise<TagItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/tags`);
  if (!res.ok) {
    throw new Error('Failed to fetch asset tags');
  }
  return res.json();
}

export async function addAssetTag(
  assetId: number,
  name: string
): Promise<{ id: number; name: string; asset_id: number; tags: TagItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/tags`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to add tag to asset');
  }
  return res.json();
}

export async function removeAssetTag(
  assetId: number,
  tagId: number
): Promise<{ message: string; asset_id: number; tag_id: number; tags: TagItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/tags/${tagId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to remove tag from asset');
  }
  return res.json();
}

export async function updateAssetTags(
  assetId: number,
  tags: string[]
): Promise<{ asset_id: number; tags: TagItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/tags`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tags }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to update asset tags');
  }
  return res.json();
}

/* Provider API keys */
export async function getApiKey(provider: string): Promise<{ key: string | null }> {
  const url = `${API_BASE_URL}/api/config/${provider}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch API key');
  }
  return res.json();
}

export async function setApiKey(provider: string, key: string): Promise<{ message: string }> {
  const url = `${API_BASE_URL}/api/config/${provider}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) {
    throw new Error('Failed to set API key');
  }
  return res.json();
}

/* ── Provider API keys (encrypted server-side) ────────────────────────── */

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

export interface GenerateAudioResponse {
  status: string;
  type: string;
  filename: string;
  url: string;
  colab?: boolean;
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

export async function fetchSettings(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE_URL}/api/settings`);
  if (!res.ok) {
    throw new Error('Failed to fetch settings');
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
  type: 'tts' | 'sfx' = 'tts',
  voiceId?: string,
  duration?: number,
): Promise<GenerateAudioResponse> {
  const params = new URLSearchParams({ prompt, type });
  if (voiceId) params.set('voice_id', voiceId);
  if (duration !== undefined) params.set('duration', duration.toString());
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

/* ── Magnific Upscaler API (#94 / #96) ──────────────────────────────── */

export interface UpscalePayload {
  image_path: string;
  scale: number;
  preset?: string;
  creativity?: number;
  resemblance?: number;
  fractality?: number;
  hdr?: number;
  category?: string;
  prompt?: string;
}

export interface UpscaleStartResponse {
  message: string;
  task_id: string;
  status: string;
  scale: number;
  preset: string;
  category: string;
  output_path: string;
  parameters: {
    creativity: number;
    resemblance: number;
    fractality: number;
    hdr: number;
    denoise: number;
    controlnet_scale: number;
  };
}

export interface UpscaleStatusResponse {
  task_id: string;
  name: string | null;
  status: string; // QUEUED | PROCESSING | COMPLETED | FAILED
  progress: number;
  error: string | null;
  logs: string | null;
  output_path: string | null;
  result_url: string | null;
}

export interface UpscalePresetDefinition {
  name: string;
  description: string;
  creativity: number;
  resemblance: number;
  fractality: number;
  hdr: number;
}

export interface UpscaleCategoryDefinition {
  label: string;
  description: string;
  prompt_keywords: string;
}

async function readErrorDetail(res: Response, fallback: string): Promise<string> {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = err?.detail;
  if (typeof detail === 'string') return detail;
  if (detail) return JSON.stringify(detail);
  return fallback;
}

/** Dispatch a Magnific-style tile upscale job. */
export async function startUpscale(payload: UpscalePayload): Promise<UpscaleStartResponse> {
  const res = await fetch(`${API_BASE_URL}/api/upscale`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Upscale request failed'));
  }
  return res.json();
}

export async function saveSettings(data: Record<string, any>): Promise<any> {
  const res = await fetch(`${API_BASE_URL}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    throw new Error('Failed to save settings');
  }
  return res.json();
}

export interface BatchExportResponse {
  message: string;
  task_id: string;
  status: string;
}

export interface ExportStatusResponse {
  task_id: string;
  status: string;
  progress: number;
  download_url?: string | null;
  filename?: string | null;
  error?: string | null;
}

/** Trigger batch export for database-backed assets by ID, including generated derivatives (#106). */
export async function startAssetBatchExport(
  assetIds: number[],
  includeDerivatives: boolean = true
): Promise<BatchExportResponse> {
  const url = `${API_BASE_URL}/api/export/batch`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ asset_ids: assetIds, include_derivatives: includeDerivatives }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to start batch export');
  }
  return res.json();
}

/** Poll progress/result for an asset batch export job (#106). */
export async function getExportStatus(taskId: string): Promise<ExportStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/export/${encodeURIComponent(taskId)}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Failed to fetch export status');
  }
  return res.json();
}

export async function startBatchExport(
  paths: string[],
  format: string = 'original'
): Promise<BatchExportResponse> {
  const url = `${API_BASE_URL}/api/storage/download-batch`;
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ paths, format }),
  });

  if (!res.ok) {
    throw new Error('Failed to start batch export');
  }
  return res.json();
}

/** Poll progress/result for an upscale job. */
export async function getUpscaleStatus(taskId: string): Promise<UpscaleStatusResponse> {
  const res = await fetch(`${API_BASE_URL}/api/upscale/status/${encodeURIComponent(taskId)}`);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to fetch upscale status'));
  }
  return res.json();
}

/** Engine preset registry (Subtle / Vivid / Wild / Custom). */
export async function fetchUpscalePresets(): Promise<Record<string, UpscalePresetDefinition>> {
  const res = await fetch(`${API_BASE_URL}/api/upscale/presets`);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to fetch upscale presets'));
  }
  const body = await res.json();
  return body.presets ?? {};
}

/** Engine content-category registry (v1 six categories). */
export async function fetchUpscaleCategories(): Promise<Record<string, UpscaleCategoryDefinition>> {
  const res = await fetch(`${API_BASE_URL}/api/upscale/categories`);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to fetch upscale categories'));
  }
  const body = await res.json();
  return body.categories ?? {};
}

export function triggerDownload(url: string, filename?: string) {
  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  if (filename) {
    a.download = filename;
  }
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/* ── Subtitle Tracks API (#109) ────────────────────────────────────────── */

export interface SubtitleTrackItem {
  id: number | string;
  asset_id?: number;
  label: string;
  language?: string | null;
  file_path?: string;
  url: string;
  format?: string;
  track_type?: string;
  created_at?: string | null;
}

export async function fetchAssetSubtitles(assetId: number | string): Promise<SubtitleTrackItem[]> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/subtitles`);
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to fetch subtitles'));
  }
  return res.json();
}

export async function uploadAssetSubtitle(
  assetId: number | string,
  file: File,
  label?: string,
  language?: string
): Promise<SubtitleTrackItem> {
  const formData = new FormData();
  formData.append('file', file);
  if (label) formData.append('label', label);
  if (language) formData.append('language', language);

  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/subtitles`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to upload subtitle file'));
  }
  return res.json();
}

export async function extractAssetSubtitles(
  assetId: number | string
): Promise<{ message: string; extracted_count: number; tracks: SubtitleTrackItem[] }> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/subtitles/extract`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to extract embedded subtitles'));
  }
  return res.json();
}

export async function deleteAssetSubtitle(
  assetId: number | string,
  trackId: number | string
): Promise<{ message: string }> {
  const res = await fetch(`${API_BASE_URL}/api/media/${assetId}/subtitles/${trackId}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(await readErrorDetail(res, 'Failed to delete subtitle track'));
  }
  return res.json();
}
