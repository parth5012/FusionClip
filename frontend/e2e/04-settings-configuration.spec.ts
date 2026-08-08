import { test, expect, API_BASE, apiGetSettings, apiSaveSettings, apiResetSecrets, navigateToTab } from './fixtures';

/**
 * Suite 4 — Settings & Configuration Console
 *
 * Tests the Settings panel: Gemini API key, ElevenLabs API key,
 * Colab tunnel endpoint URL configuration, persistence via
 * the encrypted server-side store (never localStorage — see C-1/WS-1).
 *
 * API keys are write-only: the server never returns key material, only
 * a `{configured, last4}` status. Tests verify against that contract.
 */
test.describe('Settings Configuration', () => {
  const testGeminiKey = 'e2e-test-gemini-key-abc123';
  const testElevenLabsKey = 'e2e-test-elevenlabs-key-xyz789';
  const testTunnelUrl = 'https://e2e-test-tunnel.trycloudflare.com';

  // The secret endpoints are unauthenticated; earlier tests' keys persist
  // server-side and would make "not configured" assertions order-dependent.
  test.beforeEach(async () => {
    await apiResetSecrets();
  });

  test('settings panel renders all configuration sections', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Configuration');

    // Should show the main heading
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    // Should show API Keys section
    await expect(page.getByText('Commercial API Keys', { exact: false })).toBeVisible();

    // Should show Colab tunnel section
    await expect(page.getByText('Remote Colab GPU Workers', { exact: false })).toBeVisible();

    // Should have Gemini key input
    const geminiInput = page.locator('input[placeholder*="Gemini" i]');
    await expect(geminiInput).toBeVisible();

    // Should have ElevenLabs key input
    const elevenLabsInput = page.locator('input[placeholder*="ElevenLabs" i]');
    await expect(elevenLabsInput).toBeVisible();
  });

  test('enter and save API keys via UI reports configured status', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    // Fill in Gemini key
    const geminiInput = page.locator('input[placeholder*="Gemini" i]');
    await geminiInput.fill(testGeminiKey);

    // Fill in ElevenLabs key
    const elevenLabsInput = page.locator('input[placeholder*="ElevenLabs" i]');
    await elevenLabsInput.fill(testElevenLabsKey);

    // Click Save API Keys button
    const saveBtn = page.locator('button').filter({ hasText: /save api keys/i });
    await saveBtn.click();

    // Wait for "Saved!" confirmation
    await expect(page.getByText('Saved!', { exact: false })).toBeVisible({ timeout: 5000 });

    // Server now reports both keys as configured (the {configured, last4}
    // contract — key material never returns to the browser).
    await expect(page.getByText('Configured', { exact: false }).first()).toBeVisible({ timeout: 5000 });

    // Verify no key material leaked into localStorage.
    const storedState = await page.evaluate(() => {
      const raw = localStorage.getItem('fusionclip-settings');
      return raw ? JSON.parse(raw) : null;
    });
    expect(storedState).toBeTruthy();
    expect(storedState.state).not.toHaveProperty('apiKeys');
  });

  test('API keys persist across page reloads via server-side store', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    // Set keys
    const geminiInput = page.locator('input[placeholder*="Gemini" i]');
    await geminiInput.fill(testGeminiKey);
    const elevenLabsInput = page.locator('input[placeholder*="ElevenLabs" i]');
    await elevenLabsInput.fill(testElevenLabsKey);
    await page.locator('button').filter({ hasText: /save api keys/i }).click();
    await expect(page.getByText('Saved!')).toBeVisible({ timeout: 5000 });

    // Reload page
    await page.reload();
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    // Inputs are write-only: they always start empty (keys are never read
    // back from the server). The "Configured" badge reflects server state.
    await expect(page.getByText('Configured', { exact: false }).first()).toBeVisible({ timeout: 5000 });
    const geminiValue = await page.locator('input[placeholder*="Gemini" i]').inputValue();
    expect(geminiValue).toBe('');
  });

  test('API key visibility toggles work (show/hide password)', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    const geminiInput = page.locator('input[placeholder*="Gemini" i]');

    // Should start as password type
    await expect(geminiInput).toHaveAttribute('type', 'password');

    // Click the eye toggle button (sibling button near the input)
    const toggleBtn = geminiInput.locator('..').locator('button');
    await toggleBtn.click();

    // Should now show as text
    await expect(geminiInput).toHaveAttribute('type', 'text');

    // Toggle back
    await toggleBtn.click();
    await expect(geminiInput).toHaveAttribute('type', 'password');
  });

  test('configure Colab tunnel URL and toggle connection status', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Configuration');
    await expect(page.getByText('System Integration Configuration')).toBeVisible({ timeout: 10000 });

    // Find tunnel URL input
    const tunnelInput = page.locator('input[placeholder*="tunnel" i], input[placeholder*="cloudflare" i], input[placeholder*="ngrok" i], input[placeholder*="endpoint" i], input[placeholder*="url" i]').last();

    if (await tunnelInput.isVisible({ timeout: 3000 }).catch(() => false)) {
      await tunnelInput.fill(testTunnelUrl);

      // Save tunnel settings
      const saveTunnelBtn = page.locator('button').filter({ hasText: /save.*tunnel|save.*colab|save.*endpoint/i }).first();
      if (await saveTunnelBtn.isVisible({ timeout: 3000 }).catch(() => false)) {
        await saveTunnelBtn.click();
        await expect(page.getByText('Saved!', { exact: false })).toBeVisible({ timeout: 5000 });
      }
    }

    // Toggle tunnel connection status
    const toggleState = page.locator('button').filter({ hasText: /connect|disconnect/i }).first();
    if (await toggleState.isVisible({ timeout: 3000 }).catch(() => false)) {
      await toggleState.click();
      await page.waitForTimeout(500);

      // Status indicator should change
      const statusText = await page.getByText(/running|connected|disconnected/i).first().textContent();
      expect(statusText).toBeTruthy();
    }
  });

  test('backend settings API roundtrip (save and retrieve)', async () => {
    const testSettings = {
      e2e_test_key: 'e2e_test_value_' + Date.now(),
      another_key: 'another_value',
    };

    // Save
    await apiSaveSettings(testSettings);

    // Retrieve
    const retrieved = await apiGetSettings();
    expect(retrieved.e2e_test_key).toBe(testSettings.e2e_test_key);
    expect(retrieved.another_key).toBe(testSettings.another_key);
  });

  test('Colab tunnel API endpoint configures and returns status', async () => {
    const res = await fetch(
      `${API_BASE}/api/colab/tunnel?url=${encodeURIComponent(testTunnelUrl)}&status=running`,
      { method: 'POST' },
    );
    expect(res.ok).toBeTruthy();

    const body = await res.json();
    expect(body.status).toBe('SUCCESS');
    expect(body.colab_url).toBe(testTunnelUrl);
    expect(body.colab_status).toBe('running');

    // Verify it persisted in settings
    const settings = await apiGetSettings();
    expect(settings.colab_tunnel_url).toBe(testTunnelUrl);
    expect(settings.colab_tunnel_status).toBe('running');
  });

  test('header reflects missing API keys warning', async ({ page }) => {
    // Clear localStorage to reset keys
    await page.goto('/');
    await page.evaluate(() => localStorage.removeItem('fusionclip-settings'));
    await page.reload();

    // Header should show "Setup API Keys" warning badge
    const header = page.locator('header');
    await expect(header.getByText('Setup API Keys', { exact: false })).toBeVisible({
      timeout: 5000,
    });
  });
});
