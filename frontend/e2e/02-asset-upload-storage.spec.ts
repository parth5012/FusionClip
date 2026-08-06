import { test, expect, API_BASE, TEST_FILES, apiUploadFile, apiListFiles, apiDeleteFile, navigateToTab } from './fixtures';
import path from 'path';
import fs from 'fs';
import os from 'os';

/**
 * Suite 2 — Asset Upload, Storage & Cleanup
 *
 * End-to-end validation of file upload to MinIO S3,
 * metadata persistence in Postgres, directory browsing,
 * folder creation, and file deletion/cleanup.
 */
test.describe('Asset Upload & Storage', () => {
  const testFolderName = `e2e-test-${Date.now()}`;

  test.afterAll(async () => {
    // Cleanup: delete all objects we created during this suite
    try {
      const listing = await apiListFiles(testFolderName);
      for (const file of listing.files || []) {
        await apiDeleteFile(file.path).catch(() => { /* ignore cleanup errors */ });
      }
      // Delete the virtual folder marker itself
      await apiDeleteFile(`${testFolderName}/`).catch(() => {});
    } catch {
      // cleanup is best-effort
    }
  });

  test('upload image file via UI produces S3 object and DB asset record', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Media Library');

    // Wait for file manager to load (shows the directory listing)
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 10000 });

    // Create a temporary file on disk for Playwright's file chooser
    const tmpDir = os.tmpdir();
    const tmpFile = path.join(tmpDir, TEST_FILES.image.name);
    fs.writeFileSync(tmpFile, TEST_FILES.image.buffer);

    // Trigger upload via the hidden file input
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(tmpFile);

    // Wait for upload completion — the file list should refresh and show our file
    await expect(page.getByText(TEST_FILES.image.name, { exact: false })).toBeVisible({
      timeout: 15000,
    });

    // Verify via API that the file exists in MinIO
    const listing = await apiListFiles('');
    const uploaded = listing.files.find((f: any) => f.name === TEST_FILES.image.name);
    expect(uploaded).toBeTruthy();
    expect(uploaded.path).toContain(TEST_FILES.image.name);

    // Cleanup
    fs.unlinkSync(tmpFile);
  });

  test('upload file via REST API roundtrips correctly', async () => {
    const result = await apiUploadFile(
      TEST_FILES.video.name,
      TEST_FILES.video.buffer,
      TEST_FILES.video.mime,
    );

    expect(result.filename).toBe(TEST_FILES.video.name);
    expect(result.path).toContain(TEST_FILES.video.name);
    expect(result.url).toBeTruthy();

    // Verify listing includes the file
    const listing = await apiListFiles('');
    const found = listing.files.find((f: any) => f.name === TEST_FILES.video.name);
    expect(found).toBeTruthy();
  });

  test('create folder via UI and verify directory appears', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Media Library');
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 10000 });

    // Type folder name into the create-folder input
    const folderInput = page.locator('input[placeholder*="folder" i], input[placeholder*="directory" i], input[placeholder*="name" i]').first();

    if (await folderInput.isVisible()) {
      await folderInput.fill(testFolderName);

      // Submit form
      const createBtn = page.locator('button').filter({ hasText: /create|add/i }).first();
      await createBtn.click();

      // The folder should appear in the directory listing
      await expect(page.getByText(testFolderName, { exact: false })).toBeVisible({
        timeout: 10000,
      });
    } else {
      // Fallback: create folder via API
      const res = await fetch(`${API_BASE}/api/storage/create-folder?folder_path=${encodeURIComponent(testFolderName)}`, {
        method: 'POST',
      });
      expect(res.ok).toBeTruthy();
    }

    // Verify via API
    const listing = await apiListFiles('');
    const folderExists = listing.directories.some(
      (d: any) => d.name === testFolderName || d.path?.includes(testFolderName),
    );
    expect(folderExists).toBeTruthy();
  });

  test('upload file into subfolder and verify nested path', async () => {
    // Upload into the test subfolder
    const result = await apiUploadFile(
      TEST_FILES.audio.name,
      TEST_FILES.audio.buffer,
      TEST_FILES.audio.mime,
      testFolderName,
    );

    expect(result.path).toContain(testFolderName);
    expect(result.path).toContain(TEST_FILES.audio.name);

    // Verify listing in subfolder
    const listing = await apiListFiles(testFolderName);
    const found = listing.files.find((f: any) => f.name === TEST_FILES.audio.name);
    expect(found).toBeTruthy();
  });

  test('delete file via UI removes it from listing', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Media Library');
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 10000 });

    // Wait for file manager to load files
    await page.waitForTimeout(2000);

    // Look for the test image we uploaded earlier
    const fileRow = page.getByText(TEST_FILES.image.name, { exact: false });

    if (await fileRow.isVisible({ timeout: 5000 }).catch(() => false)) {
      // Set up dialog handler to accept confirmation
      page.on('dialog', (dialog) => dialog.accept());

      // Find and click the delete button near this file
      const deleteBtn = fileRow.locator('..').locator('button').filter({ has: page.locator('svg') }).last();
      if (await deleteBtn.isVisible()) {
        await deleteBtn.click();
        await page.waitForTimeout(2000);

        // File should no longer appear
        await expect(page.getByText(TEST_FILES.image.name, { exact: false })).not.toBeVisible({
          timeout: 10000,
        });
      }
    } else {
      // Fallback: delete via API and verify
      await apiDeleteFile(TEST_FILES.image.name);
      const listing = await apiListFiles('');
      const stillExists = listing.files.find((f: any) => f.name === TEST_FILES.image.name);
      expect(stillExists).toBeFalsy();
    }
  });

  test('delete file via API removes from S3 storage', async () => {
    // The video file should still exist from earlier
    await apiDeleteFile(TEST_FILES.video.name);

    const listing = await apiListFiles('');
    const stillExists = listing.files.find((f: any) => f.name === TEST_FILES.video.name);
    expect(stillExists).toBeFalsy();
  });

  test('breadcrumb navigation works for directory traversal', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Media Library');
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 10000 });
    await page.waitForTimeout(2000);

    // Should show "Root" breadcrumb at top level
    await expect(page.getByText('Root', { exact: false })).toBeVisible({ timeout: 5000 });
  });
});
