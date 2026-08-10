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
  created_at: string | null;
  updated_at: string | null;
}

export interface TaskListResponse {
  total: number;
  page: number;
  page_size: number;
  tasks: TaskListItem[];
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

export async function fetchTasks(
  page = 1,
  pageSize = 50,
  status?: string,
  taskType?: string,
): Promise<TaskListResponse> {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });
  if (status) params.set('status', status);
  if (taskType) params.set('task_type', taskType);
  const url = `${API_BASE_URL}/api/tasks/list?${params.toString()}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error('Failed to fetch tasks');
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
