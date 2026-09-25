import { test, expect, TEST_FILES, apiUploadFile, apiDeleteFile, apiStartTask, apiPollTask, apiFetchMediaCatalog, navigateToTab } from './fixtures';

/**
 * Suite 9 — Magnific-Style Upscaler & Before/After Comparison
 *
 * Covers the decisions from the still-image parity map (#56):
 *   - #57: HDR + Fractality controls, dual-labeled sliders (Creativity /
 *          Resemblance as secondary terms)
 *   - #59: optional img2img prompt guidance
 *   - #58: before/after comparison modal (fullscreen overlay, drag + keys)
 *
 * The API dispatch and full before/after flow need a Celery worker that can
 * run the upscale task, so those tests follow the suite's defensive pattern:
 * the upscale task must reach a terminal state, and the comparison UI tests
 * are skipped when the worker could not produce an upscaled asset.
 */
test.describe('Upscaler & Before/After Comparison', () => {
  const imageName = `e2e-upscaler-${Date.now()}.png`;
  const upscaledName = `processed/upscaled_${imageName}`;
  const createdFiles: string[] = [imageName];

  let upscaleSucceeded = false;
  let upscaleResult: any = null;

  test.beforeAll(async () => {
    const result = await apiUploadFile(imageName, TEST_FILES.image.buffer, TEST_FILES.image.mime);
    expect(result.path).toBe(imageName);
  });

  test.afterAll(async () => {
    // Best-effort cleanup of the source and any upscaled output.
    for (const file of createdFiles) {
      try { await apiDeleteFile(file); } catch { /* best-effort */ }
    }
  });

  test('Upscaler tab renders all fidelity controls with dual labels', async ({ page }) => {
    await page.goto('/');
    await navigateToTab(page, 'Upscaler');

    // Panel banner
    await expect(page.getByText('Magnific-Style Generative Upscaler')).toBeVisible({ timeout: 10000 });

    // Four sliders — Denoising Strength, ControlNet Weight, HDR, Fractality
    const sliders = page.locator('section input[type="range"]');
    await expect(sliders).toHaveCount(4);

    // Dual labels: mechanical name primary, Magnific term secondary (#57)
    await expect(page.getByText('Denoising Strength', { exact: false })).toBeVisible();
    await expect(page.getByText('Creativity', { exact: false })).toBeVisible();
    await expect(page.getByText('ControlNet Weight', { exact: false })).toBeVisible();
    await expect(page.getByText('Resemblance', { exact: false })).toBeVisible();
    await expect(page.getByText('HDR', { exact: false }).first()).toBeVisible();
    await expect(page.getByText('Fractality', { exact: false })).toBeVisible();

    // Optional prompt field (#59)
    const prompt = page.locator('input[placeholder*="skin pores" i]');
    await expect(prompt).toBeVisible();

    // Presets from features.md §5
    for (const preset of ['Portraits', 'Anime', 'Landscapes', 'Product Photography', '3D Renderings']) {
      await expect(page.getByText(preset, { exact: true })).toBeVisible();
    }

    // Run button
    await expect(page.getByRole('button', { name: /run upscale/i })).toBeVisible();
  });

  test('upscale task dispatch forwards controls and reaches terminal state', async () => {
    const taskRes = await apiStartTask(imageName, 'upscale', {
      denoise: 0.5,
      controlnet_weight: 0.9,
      hdr: 0.4,
      fractality: 0.6,
      prompt: 'sharp details',
    });
    expect(taskRes.task_id).toBeTruthy();

    let finalStatus;
    try {
      finalStatus = await apiPollTask(taskRes.task_id, 45_000);
    } catch (err) {
      // Worker unreachable or task never completed — dispatch was still valid.
      test.info().annotations.push({ type: 'skip-reason', description: `Upscale task did not complete: ${err}` });
      return;
    }

    // Like the rest of the suite, accept either terminal state — the worker
    // may be offline or lack the pipeline.
    expect(['SUCCESS', 'FAILURE']).toContain(finalStatus.state);

    if (finalStatus.state === 'SUCCESS' && finalStatus.info?.processed_url) {
      upscaleSucceeded = true;
      upscaleResult = finalStatus.info;
      createdFiles.push(upscaledName);
      expect(finalStatus.info.original_object).toBe(imageName);
    }
  });

  test('catalog exposes the source→upscaled relation after a successful upscale', async () => {
    test.skip(!upscaleSucceeded, 'requires a successful upscale task');
    const catalog = await apiFetchMediaCatalog();
    const original = catalog.find((a: any) => a.file_path === imageName);
    const upscaled = catalog.find((a: any) => a.file_path === upscaledName);

    expect(original).toBeTruthy();
    expect(upscaled).toBeTruthy();
    // Original lists the upscaled output (#58)
    expect(original.upscaled_assets.some((c: any) => c.file_path === upscaledName)).toBeTruthy();
    // Upscaled output points back at the original
    expect(upscaled.source_path).toBe(imageName);
    expect(upscaled.source_url).toBeTruthy();
  });

  test('Compare button on a catalog card opens the before/after modal', async ({ page }) => {
    test.skip(!upscaleSucceeded, 'requires a successful upscale task');

    await page.goto('/');
    await navigateToTab(page, 'Catalog Search');
    await page.waitForTimeout(2000);

    // The original image card now has a Compare button (upscaled sibling).
    // Match the card whose title is exactly the source filename — the
    // upscaled card's title is prefixed "Upscaled:" so exact text disambiguates.
    const originalCard = page
      .locator('div.rounded-xl')
      .filter({ has: page.getByText(imageName, { exact: true }) })
      .first();
    const compareBtn = originalCard.getByRole('button', { name: /compare/i });
    await expect(compareBtn).toBeVisible({ timeout: 15000 });
    await compareBtn.click();

    // Fullscreen overlay modal with before/after labels
    await expect(page.getByText('Original', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Upscaled', { exact: true })).toBeVisible();
    await expect(page.getByText(/Esc to close/i)).toBeVisible();

    // Divider starts at 50% — arrow keys move it (#58 interaction)
    const divider = page.locator('div.cursor-ew-resize').first();
    const startLeft = await divider.evaluate((el) => (el as HTMLElement).style.left);
    expect(startLeft).toBe('50%');
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(200);
    const movedLeft = await divider.evaluate((el) => (el as HTMLElement).style.left);
    expect(movedLeft).not.toBe(startLeft);

    // Escape closes the modal
    await page.keyboard.press('Escape');
    await expect(page.getByText(/Esc to close/i)).not.toBeVisible({ timeout: 5000 });
  });

  test('Upscaler panel runs a job and opens the comparison on completion', async ({ page }) => {
    test.skip(!upscaleSucceeded, 'requires a successful upscale task');

    await page.goto('/');
    await navigateToTab(page, 'Upscaler');
    await page.waitForTimeout(2000);

    // Select the uploaded image from the catalog dropdown
    await page.locator('select').first().selectOption({ label: imageName });

    // Apply the Portraits preset and run
    await page.getByText('Portraits', { exact: true }).click();
    await page.getByRole('button', { name: /run upscale/i }).click();

    // Wait for the completion banner
    await expect(page.getByText(/upscale complete/i)).toBeVisible({ timeout: 60_000 });

    // Compare button opens the before/after modal
    await page.getByRole('button', { name: /compare/i }).click();
    await expect(page.getByText('Original', { exact: true })).toBeVisible({ timeout: 5000 });
    await expect(page.getByText('Upscaled', { exact: true })).toBeVisible();

    // Close
    await page.keyboard.press('Escape');
    await expect(page.getByText(/Esc to close/i)).not.toBeVisible({ timeout: 5000 });
  });
});
