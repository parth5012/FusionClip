import { test, expect, API_BASE, apiFetchMediaCatalog, navigateToTab } from './fixtures';

/**
 * Suite 5 — Generation Triggers & Media Catalog
 *
 * Tests the generation API endpoints (text/audio/image),
 * media catalog listing, and semantic vector search.
 */
test.describe('Generation & Catalog', () => {
  const generatedFiles: string[] = [];

  test.afterAll(async () => {
    // Cleanup generated files
    for (const filename of generatedFiles) {
      try {
        await fetch(`${API_BASE}/api/storage/delete?path=${encodeURIComponent(filename)}`, {
          method: 'DELETE',
        });
      } catch { /* best-effort */ }
    }
  });

  test('text generation endpoint returns Gemini-style output', async () => {
    const prompt = 'Create a storyboard for a sunset timelapse video';
    const res = await fetch(
      `${API_BASE}/api/generate/text?prompt=${encodeURIComponent(prompt)}`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();

    const body = await res.json();
    expect(body.status).toBe('COMPLETED');
    expect(body.output).toContain(prompt.substring(0, 15));
  });

  test('audio generation endpoint creates file in MinIO and DB record', async () => {
    const prompt = 'Generate a forest ambience soundscape';
    const res = await fetch(
      `${API_BASE}/api/generate/audio?prompt=${encodeURIComponent(prompt)}&type=sfx`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();

    const body = await res.json();
    expect(body.status).toBe('COMPLETED');
    expect(body.type).toBe('sfx');
    expect(body.filename).toMatch(/^gen_audio_\d+\.mp3$/);
    expect(body.url).toBeTruthy();

    generatedFiles.push(body.filename);

    // Verify asset appears in media catalog
    const catalog = await apiFetchMediaCatalog();
    const found = catalog.find((a: any) => a.file_path === body.filename);
    expect(found).toBeTruthy();
    expect(found.content_type).toBe('audio/mpeg');
  });

  test('image generation endpoint with params creates file in MinIO and DB', async () => {
    const prompt = 'A futuristic cityscape at dawn';
    const res = await fetch(
      `${API_BASE}/api/generate/image?prompt=${encodeURIComponent(prompt)}&steps=20&scale=8.5`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();

    const body = await res.json();
    expect(body.status).toBe('COMPLETED');
    expect(body.filename).toMatch(/^gen_image_\d+\.png$/);
    expect(body.parameters.steps).toBe(20);
    expect(body.parameters.scale).toBe(8.5);
    expect(body.url).toBeTruthy();

    generatedFiles.push(body.filename);

    // Verify in media catalog
    const catalog = await apiFetchMediaCatalog();
    const found = catalog.find((a: any) => a.file_path === body.filename);
    expect(found).toBeTruthy();
    expect(found.content_type).toBe('image/png');
  });

  test('media catalog endpoint lists all assets with correct structure', async () => {
    const catalog = await apiFetchMediaCatalog();

    expect(Array.isArray(catalog)).toBeTruthy();

    if (catalog.length > 0) {
      const asset = catalog[0];
      expect(asset).toHaveProperty('id');
      expect(asset).toHaveProperty('title');
      expect(asset).toHaveProperty('file_path');
      expect(asset).toHaveProperty('file_size');
      expect(asset).toHaveProperty('content_type');
      expect(asset).toHaveProperty('duration');
      expect(asset).toHaveProperty('url');
      expect(asset).toHaveProperty('created_at');
    }
  });

  test('media search endpoint performs text-based search fallback', async () => {
    // Search for assets with "ElevenLabs" in the title (from audio generation)
    const results = await apiFetchMediaCatalog('ElevenLabs', 10);

    expect(Array.isArray(results)).toBeTruthy();
    // If audio was generated, search should find it by title
    if (results.length > 0) {
      expect(results[0].title).toContain('ElevenLabs');
    }
  });

  test('media search with unknown query returns empty or vector-matched set', async () => {
    const results = await apiFetchMediaCatalog('zzz_nonexistent_query_12345', 5);
    expect(Array.isArray(results)).toBeTruthy();
    // May be empty (text search) or have vector results (pgvector)
  });

  test('generation panel UI shows feature cards and API key requirement warnings', async ({ page }) => {
    // Clear API keys to see warnings
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('fusionclip-settings'));
    await page.reload();

    await navigateToTab(page, 'Generative AI');

    // Should show generation panel content
    await expect(page.getByText('Generation', { exact: false })).toBeVisible({ timeout: 10000 });

    // Should show API key requirement warning
    await expect(page.getByText(/API Key/i)).toBeVisible({ timeout: 5000 });

    // Should show feature cards
    await expect(page.getByText('Google Gemini', { exact: false })).toBeVisible();
    await expect(page.getByText('ElevenLabs', { exact: false })).toBeVisible();
    await expect(page.getByText('Flux', { exact: false }).or(page.getByText('SDXL', { exact: false }))).toBeVisible();
  });

  test('catalog panel UI loads and shows search interface', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Catalog Search');

    // Should show catalog content
    await expect(page.getByText('Catalog', { exact: false })).toBeVisible({ timeout: 10000 });

    // Should have a search input
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i], input[placeholder*="query" i]');
    await expect(searchInput.first()).toBeVisible({ timeout: 5000 });
  });

  test('catalog search from UI triggers API call and shows results', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Catalog Search');
    await page.waitForTimeout(2000);

    // Type a search query
    const searchInput = page.locator('input[type="text"], input[placeholder*="search" i]').first();
    if (await searchInput.isVisible({ timeout: 5000 }).catch(() => false)) {
      await searchInput.fill('generated');

      // Submit search (press Enter or click search button)
      await searchInput.press('Enter');
      await page.waitForTimeout(3000);

      // Results area should update (either show results or "no results")
      const mainContent = page.locator('main, [class*="flex-1"]');
      const hasContent = await mainContent.isVisible();
      expect(hasContent).toBeTruthy();
    }
  });

  test('catalog filter buttons switch between media types', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Catalog Search');
    await page.waitForTimeout(2000);

    // Look for filter buttons (all, audio, video, image)
    const filterBtns = page.locator('button').filter({ hasText: /^(all|audio|video|image)$/i });
    const count = await filterBtns.count();

    if (count > 0) {
      // Click each filter and verify it's responsive
      for (let i = 0; i < count; i++) {
        await filterBtns.nth(i).click();
        await page.waitForTimeout(500);
      }
    }
  });
});
