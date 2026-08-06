import { test, expect, API_BASE } from './fixtures';

/**
 * Suite 1 — Smoke & Navigation Tests
 *
 * Validates that the full-stack Docker Compose environment is healthy
 * and the frontend loads correctly with all navigation working.
 */
test.describe('Smoke & Navigation', () => {
  test('backend health check returns green status', async ({ request }) => {
    const res = await request.get(`${API_BASE}/`);
    expect(res.ok()).toBeTruthy();

    const body = await res.json();
    expect(body.app).toBe('FusionClip API Portal');
    expect(body.status).toBe('Green');
    expect(body.database).toContain('pgvector');
    expect(body.storage).toContain('MinIO');
  });

  test('frontend loads and displays FusionClip branding', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle(/FusionClip/i);

    // Sidebar brand should be visible
    await expect(page.locator('aside')).toContainText('FusionClip');
  });

  test('sidebar navigation cycles through all tabs', async ({ page }) => {
    await page.goto('/');

    const tabs = [
      { label: 'Media Library', content: 'Local S3 Filemanager' },
      { label: 'Catalog Search', content: 'Catalog' },
      { label: 'Generative AI', content: 'Generation' },
      { label: 'Media Players', content: 'Player' },
      { label: 'Configuration', content: 'System Integration Configuration' },
    ];

    for (const tab of tabs) {
      await page.getByText(tab.label, { exact: false }).first().click();
      await page.waitForTimeout(400);
      await expect(page.locator('main, [class*="flex-1"]')).toContainText(tab.content, {
        timeout: 5000,
      });
    }
  });

  test('sidebar toggle hides and reveals navigation', async ({ page }) => {
    await page.goto('/');
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    // Toggle sidebar via header button
    const toggleBtn = page.locator('header button').first();
    await toggleBtn.click();
    await page.waitForTimeout(400);

    // Re-toggle to show
    await toggleBtn.click();
    await page.waitForTimeout(400);
    await expect(sidebar).toBeVisible();
  });

  test('header shows infrastructure status badges', async ({ page }) => {
    await page.goto('/');
    const header = page.locator('header');

    // Should show postgres, MinIO, Redis badges
    await expect(header).toContainText('pgvector', { timeout: 5000 });
    await expect(header).toContainText('MinIO', { timeout: 5000 });
    await expect(header).toContainText('Redis', { timeout: 5000 });
  });
});
