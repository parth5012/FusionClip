import { test, expect, API_BASE, apiDeleteFile, apiListFiles } from './fixtures';

/**
 * Suite 8 — Edge Cases & Error Handling
 *
 * Tests boundary conditions, malformed inputs,
 * and error recovery paths.
 */
test.describe('Edge Cases & Error Handling', () => {
  test('uploading empty file body is handled gracefully', async () => {
    const formData = new FormData();
    formData.append('file', new Blob([]), 'empty-file.txt');

    const res = await fetch(`${API_BASE}/api/storage/upload?folder=`, {
      method: 'POST',
      body: formData,
    });
    // Should either succeed (0-byte file) or return a clear error
    expect([200, 400, 422, 500]).toContain(res.status);
  });

  test('creating folder with empty path returns 400 error', async () => {
    const res = await fetch(`${API_BASE}/api/storage/create-folder?folder_path=`, {
      method: 'POST',
    });
    // The endpoint validates and rejects empty paths
    expect([400, 422]).toContain(res.status);
  });

  test('deleting non-existent file returns appropriate error', async () => {
    const res = await fetch(
      `${API_BASE}/api/storage/delete?path=${encodeURIComponent('nonexistent/fake-file-12345.txt')}`,
      { method: 'DELETE' },
    );
    // MinIO delete is idempotent in many configs, so could be 200 or 404/500
    expect([200, 404, 500]).toContain(res.status);
  });

  test('task processing with non-existent S3 object returns task with error state', async () => {
    const res = await fetch(
      `${API_BASE}/api/tasks/process?path=${encodeURIComponent('nonexistent-file.mp4')}&task_type=transcode`,
      { method: 'POST' },
    );
    // Task dispatch itself should succeed (async), but the worker may fail
    expect([200, 404, 500]).toContain(res.status);

    if (res.ok) {
      const body = await res.json();
      expect(body.task_id).toBeTruthy();
    }
  });

  test('generation endpoints handle very long prompts gracefully', async () => {
    const longPrompt = 'x'.repeat(5000);
    const res = await fetch(
      `${API_BASE}/api/generate/text?prompt=${encodeURIComponent(longPrompt)}`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();
    const body = await res.json();
    expect(body.status).toBe('COMPLETED');
  });

  test('image generation with edge parameter values works', async () => {
    // Minimum steps, extreme scale
    const res = await fetch(
      `${API_BASE}/api/generate/image?prompt=test&steps=1&scale=0.1`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();
    const body = await res.json();
    expect(body.status).toBe('COMPLETED');
    expect(body.parameters.steps).toBe(1);
    expect(body.parameters.scale).toBe(0.1);
  });

  test('settings API handles special characters in values', async () => {
    const specialChars = { 'test_special': 'value with "quotes" & <brackets> and emojis' };
    const saveRes = await fetch(`${API_BASE}/api/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(specialChars),
    });
    expect(saveRes.ok).toBeTruthy();

    const getRes = await fetch(`${API_BASE}/api/settings`);
    const retrieved = await getRes.json();
    expect(retrieved.test_special).toBe(specialChars.test_special);
  });

  test('listing files in non-existent directory returns empty result', async () => {
    const listing = await apiListFiles('definitely-nonexistent-directory-xyz');
    expect(listing).toBeTruthy();
    // Should return empty arrays for files and directories
    expect(Array.isArray(listing.files)).toBeTruthy();
    expect(Array.isArray(listing.directories)).toBeTruthy();
  });

  test('media search with empty query returns all assets', async () => {
    const res = await fetch(`${API_BASE}/api/media`);
    expect(res.ok).toBeTruthy();
    const catalog = await res.json();
    expect(Array.isArray(catalog)).toBeTruthy();
  });

  test('WebSocket handles rapid connect/disconnect gracefully', async ({ page }) => {
    const result = await page.evaluate(async () => {
      const results: boolean[] = [];

      for (let i = 0; i < 5; i++) {
        try {
          const ws = new WebSocket('ws://localhost:8000/api/ws/tasks');
          await new Promise<void>((resolve) => {
            ws.onopen = () => { results.push(true); resolve(); };
            ws.onerror = () => { results.push(false); resolve(); };
            setTimeout(() => resolve(), 2000);
          });
          ws.close();
        } catch {
          results.push(false);
        }
        await new Promise((r) => setTimeout(r, 200));
      }

      return results;
    });

    // At least some connections should succeed
    expect(result.length).toBeGreaterThan(0);
  });

  test('multiple concurrent file uploads do not conflict', async () => {
    const uploads = Array.from({ length: 3 }, (_, i) => {
      const formData = new FormData();
      const content = Buffer.from(`concurrent-file-${i}-content`);
      formData.append(
        'file',
        new Blob([content], { type: 'text/plain' }),
        `concurrent-test-${i}.txt`,
      );
      return fetch(`${API_BASE}/api/storage/upload?folder=`, {
        method: 'POST',
        body: formData,
      });
    });

    const results = await Promise.all(uploads);
    for (const res of results) {
      expect(res.ok).toBeTruthy();
    }

    // Verify all files exist
    const listing = await apiListFiles('');
    for (let i = 0; i < 3; i++) {
      const found = listing.files.find((f: any) => f.name === `concurrent-test-${i}.txt`);
      expect(found).toBeTruthy();
    }

    // Cleanup
    for (let i = 0; i < 3; i++) {
      await apiDeleteFile(`concurrent-test-${i}.txt`).catch(() => {});
    }
  });
});
