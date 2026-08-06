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
