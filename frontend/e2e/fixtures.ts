import { test as base, expect, Page } from '@playwright/test';

/* ------------------------------------------------------------------ */
/*  Shared constants for the FusionClip E2E suite                     */
/* ------------------------------------------------------------------ */

export const API_BASE = process.env.E2E_API_URL || 'http://localhost:8000';
export const FRONTEND_BASE = process.env.E2E_BASE_URL || 'http://localhost:3000';
export const WS_URL = `ws://localhost:8000/api/ws/tasks`;

/* A minimal valid PNG (1×1 red pixel) used as an upload fixture */
const PNG_HEADER = Buffer.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, // PNG signature
  0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52, // IHDR chunk
  0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
  0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
  0xde, 0x00, 0x00, 0x00, 0x0c, 0x49, 0x44, 0x41,
  0x54, 0x08, 0xd7, 0x63, 0xf8, 0xcf, 0xc0, 0x00,
  0x00, 0x00, 0x02, 0x00, 0x01, 0xe2, 0x21, 0xbc,
  0x33, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e,
  0x44, 0xae, 0x42, 0x60, 0x82,
]);

/** MP4 stub (ftyp atom only — enough for backend to accept upload) */
const MP4_STUB = Buffer.from([
  0x00, 0x00, 0x00, 0x1c, 0x66, 0x74, 0x79, 0x70, // ftyp atom
  0x69, 0x73, 0x6f, 0x6d, 0x00, 0x00, 0x02, 0x00,
  0x69, 0x73, 0x6f, 0x6d, 0x69, 0x73, 0x6f, 0x32,
  0x6d, 0x70, 0x34, 0x31,
]);

/** WAV stub (minimal RIFF header) */
const WAV_STUB = Buffer.from([
  0x52, 0x49, 0x46, 0x46, // RIFF
  0x24, 0x00, 0x00, 0x00, // file size - 8
  0x57, 0x41, 0x56, 0x45, // WAVE
  0x66, 0x6d, 0x74, 0x20, // fmt
  0x10, 0x00, 0x00, 0x00, // chunk size
  0x01, 0x00, 0x01, 0x00, // PCM, mono
  0x44, 0xac, 0x00, 0x00, // 44100 Hz
  0x88, 0x58, 0x01, 0x00, // byte rate
  0x02, 0x00, 0x10, 0x00, // block align, bits/sample
  0x64, 0x61, 0x74, 0x61, // data
  0x00, 0x00, 0x00, 0x00, // data size (empty)
]);

export const TEST_FILES = {
  image: { name: 'e2e-test-image.png', buffer: PNG_HEADER, mime: 'image/png' },
  video: { name: 'e2e-test-video.mp4', buffer: MP4_STUB, mime: 'video/mp4' },
  audio: { name: 'e2e-test-audio.wav', buffer: WAV_STUB, mime: 'audio/wav' },
} as const;

/* ------------------------------------------------------------------ */
/*  API helpers (hit the FastAPI backend directly for setup/teardown)  */
/* ------------------------------------------------------------------ */

/** Upload a file via the REST API (bypasses UI for setup speed) */
export async function apiUploadFile(
  name: string,
  content: Buffer,
  contentType: string,
  folder = '',
): Promise<{ filename: string; path: string; url: string }> {
  const formData = new FormData();
  // Wrap in Uint8Array so BlobPart is valid across all TS lib configs
  // (Buffer is a Uint8Array subclass but not always accepted as BlobPart).
  formData.append('file', new Blob([new Uint8Array(content)], { type: contentType }), name);

  const res = await fetch(
    `${API_BASE}/api/storage/upload?folder=${encodeURIComponent(folder)}`,
    { method: 'POST', body: formData },
  );
  if (!res.ok) throw new Error(`API upload failed: ${res.status} ${await res.text()}`);
  return res.json();
}

/** List files from the API */
export async function apiListFiles(
  prefix = '',
): Promise<{ current_dir: string; directories: any[]; files: any[] }> {
  const res = await fetch(`${API_BASE}/api/storage/list?prefix=${encodeURIComponent(prefix)}`);
  if (!res.ok) throw new Error(`API list failed: ${res.status}`);
  return res.json();
}

/** Delete a file via the API */
export async function apiDeleteFile(path: string): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/storage/delete?path=${encodeURIComponent(path)}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`API delete failed: ${res.status}`);
}

/** Start a processing task via the API */
export async function apiStartTask(
  path: string,
  taskType = 'transcode',
): Promise<{ task_id: string; status: string }> {
  const res = await fetch(
    `${API_BASE}/api/tasks/process?path=${encodeURIComponent(path)}&task_type=${encodeURIComponent(taskType)}`,
    { method: 'POST' },
  );
  if (!res.ok) throw new Error(`API start task failed: ${res.status}`);
  return res.json();
}

/** Poll task status until terminal state */
export async function apiPollTask(
  taskId: string,
  timeoutMs = 30_000,
): Promise<{ id: string; state: string; info: any }> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const res = await fetch(`${API_BASE}/api/tasks/status/${taskId}`);
    if (!res.ok) throw new Error(`Task status failed: ${res.status}`);
    const data = await res.json();
    if (['SUCCESS', 'FAILURE'].includes(data.state)) return data;
    await new Promise((r) => setTimeout(r, 1000));
  }
  throw new Error(`Task ${taskId} did not complete within ${timeoutMs}ms`);
}

/** Get all settings */
export async function apiGetSettings(): Promise<Record<string, string>> {
  const res = await fetch(`${API_BASE}/api/settings`);
  if (!res.ok) throw new Error(`API get settings failed: ${res.status}`);
  return res.json();
}

/** Save settings */
export async function apiSaveSettings(data: Record<string, string>): Promise<void> {
  const res = await fetch(`${API_BASE}/api/settings`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(`API save settings failed: ${res.status}`);
}

/** Remove all stored secrets (test isolation — the secret endpoints are
 *  unauthenticated, so earlier tests' keys persist server-side and would
 *  make later tests' "not configured" assertions order-dependent. */
export async function apiResetSecrets(): Promise<void> {
  for (const provider of ['gemini', 'elevenlabs']) {
    await fetch(`${API_BASE}/api/settings/secrets/${provider}`, { method: 'DELETE' });
  }
}

/** Fetch media catalog */
export async function apiFetchMediaCatalog(
  query = '',
  limit = 20,
): Promise<any[]> {
  const url = query
    ? `${API_BASE}/api/media/search?query=${encodeURIComponent(query)}&limit=${limit}`
    : `${API_BASE}/api/media`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`API media catalog failed: ${res.status}`);
  return res.json();
}

/* ------------------------------------------------------------------ */
/*  Navigation helpers                                                */
/* ------------------------------------------------------------------ */

/** Navigate to a specific sidebar tab by clicking its menu item */
export async function navigateToTab(page: Page, tabLabel: string) {
  // Ensure sidebar is visible on all viewports
  const sidebar = page.locator('aside');
  if (!(await sidebar.isVisible())) {
    await page.locator('button[aria-label="Toggle Sidebar"]').click();
    await sidebar.waitFor({ state: 'visible', timeout: 5000 });
  }
  await page.getByText(tabLabel, { exact: false }).first().click();
  // Allow render to settle
  await page.waitForTimeout(500);
}

/* Re-export base test + expect for convenience */
export { base as test, expect };
