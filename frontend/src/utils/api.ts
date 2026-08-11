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
  logs: string | null;
  traceback: string | null;
  error_type: string | null;
  retry_count: number;
  max_retries: number;
  last_retry_at: string | null;
  created_at: string | null;
  updated_at: string | null;
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

export async function startUpscale(
  path: string,
  params: {
    denoising_strength: number;
    controlnet_weight: number;
    preset: string;
    preview: boolean;
  }
): Promise<TaskResponse> {
  const url = `${API_BASE_URL}/api/upscale?path=${encodeURIComponent(path)}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    throw new Error('Failed to start upscale task');
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
  if (taskType) params.set('type', taskType);
  if (search) params.set('search', search);
  if (errorType) params.set('error_type', errorType);
  const url = `${API_BASE_URL}/api/tasks/list?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch tasks');
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

export async function fetchSettings(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE_URL}/api/settings`);
  if (!res.ok) {
    throw new Error('Failed to fetch settings');
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