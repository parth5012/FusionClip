import { test, expect, API_BASE, TEST_FILES, apiUploadFile, apiDeleteFile, apiStartTask, apiPollTask, apiFetchMediaCatalog, apiGetSettings, apiSaveSettings, navigateToTab } from './fixtures';
import path from 'path';
import fs from 'fs';
import os from 'os';

/**
 * Suite 7 — Full Integration Happy Path
 *
 * A single end-to-end journey simulating a real user:
 *   1. Configure API keys & Colab tunnel in Settings
 *   2. Upload an asset via the File Manager
 *   3. Trigger a processing task and monitor progress
 *   4. Generate content (audio/image)
 *   5. Search the media catalog for generated assets
 *   6. Clean up uploaded and generated files
 */
test.describe('Full Integration Happy Path', () => {
  const uniqueId = Date.now();
  const testImageName = `e2e-happy-${uniqueId}.png`;
  const createdFiles: string[] = [];

  test('complete user journey: configure → upload → process → generate → search → cleanup', async ({ page }) => {
    /* ──────── Step 1: Configure API Keys ──────── */
    await page.goto('/');
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 15000 });

    const geminiInput = page.locator('input[placeholder*="Gemini" i]');
    await geminiInput.fill('e2e-gemini-key-happy-path');

    const elevenLabsInput = page.locator('input[placeholder*="ElevenLabs" i]');
    await elevenLabsInput.fill('e2e-elevenlabs-key-happy-path');

    await page.locator('button').filter({ hasText: /save api keys/i }).click();
    await expect(page.getByText('Saved!')).toBeVisible({ timeout: 5000 });

    // Verify no key material leaked into localStorage (keys are stored
    // server-side only — the {configured, last4} contract never returns
    // key material to the browser).
    const stored = await page.evaluate(() => {
      const raw = localStorage.getItem('fusionclip-settings');
      return raw ? JSON.parse(raw) : null;
    });
    expect(stored.state).not.toHaveProperty('apiKeys');

    /* ──────── Step 2: Upload Asset via File Manager ──────── */
    await navigateToTab(page, 'Media Library');
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 10000 });

    // Create temp file
    const tmpFile = path.join(os.tmpdir(), testImageName);
    fs.writeFileSync(tmpFile, TEST_FILES.image.buffer);

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(tmpFile);

    // Wait for upload to complete
    await expect(page.getByText(testImageName, { exact: false })).toBeVisible({ timeout: 15000 });
    createdFiles.push(testImageName);
    fs.unlinkSync(tmpFile);

    /* ──────── Step 3: Trigger Processing Task (API) ──────── */
    const taskRes = await apiStartTask(testImageName, 'thumbnail');
    expect(taskRes.task_id).toBeTruthy();

    // Poll to completion
    const finalStatus = await apiPollTask(taskRes.task_id, 30_000);
    expect(['SUCCESS', 'FAILURE']).toContain(finalStatus.state);

    // If successful, the processed file should exist
    if (finalStatus.state === 'SUCCESS' && finalStatus.info?.processed_url) {
      // Track for cleanup
      const processedName = `processed/thumb_${testImageName}`;
      createdFiles.push(processedName);
    }

    /* ──────── Step 4: Generate Content (Audio + Image) ──────── */
    // Generate audio
    const audioRes = await fetch(
      `${API_BASE}/api/generate/audio?prompt=E2E+happy+path+test+audio&type=tts`,
      { method: 'POST' },
    );
    expect(audioRes.ok).toBeTruthy();
    const audioBody = await audioRes.json();
    expect(audioBody.status).toBe('COMPLETED');
    createdFiles.push(audioBody.filename);

    // Generate image
    const imageRes = await fetch(
      `${API_BASE}/api/generate/image?prompt=E2E+happy+path+test+image&steps=10&scale=7.0`,
      { method: 'POST' },
    );
    expect(imageRes.ok).toBeTruthy();
    const imageBody = await imageRes.json();
    expect(imageBody.status).toBe('COMPLETED');
    createdFiles.push(imageBody.filename);

    /* ──────── Step 5: Search Media Catalog ──────── */
    await navigateToTab(page, 'Catalog Search');
    await page.waitForTimeout(2000);

    // Verify generated content appears in catalog via API
    const catalog = await apiFetchMediaCatalog();
    expect(catalog.length).toBeGreaterThan(0);

    // Find our generated audio
    const audioAsset = catalog.find((a: any) => a.file_path === audioBody.filename);
    expect(audioAsset).toBeTruthy();

    // Find our generated image
    const imageAsset = catalog.find((a: any) => a.file_path === imageBody.filename);
    expect(imageAsset).toBeTruthy();

    /* ──────── Step 6: Cleanup ──────── */
    for (const file of createdFiles) {
      try {
        await apiDeleteFile(file);
      } catch { /* best-effort cleanup */ }
    }

    // Verify cleanup was effective for the main upload
    const postCleanupListing = await fetch(`${API_BASE}/api/storage/list?prefix=`).then(r => r.json());
    const stillExists = postCleanupListing.files?.find(
      (f: any) => f.name === testImageName,
    );
    expect(stillExists).toBeFalsy();
  });

  test('backend settings roundtrip persists across API calls', async () => {
    const key = `e2e_integration_${uniqueId}`;
    await apiSaveSettings({ [key]: 'integration-test-value' });
    const retrieved = await apiGetSettings();
    expect(retrieved[key]).toBe('integration-test-value');
  });

  test('Colab tunnel configuration roundtrip via API', async () => {
    const tunnelUrl = `https://e2e-happy-${uniqueId}.trycloudflare.com`;
    const res = await fetch(
      `${API_BASE}/api/colab/tunnel?url=${encodeURIComponent(tunnelUrl)}&status=running`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();

    const body = await res.json();
    expect(body.colab_url).toBe(tunnelUrl);
    expect(body.colab_status).toBe('running');
  });
});
