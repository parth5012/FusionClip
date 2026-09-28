import {
  test,
  expect,
  TEST_FILES,
  apiUploadFile,
  apiDeleteFile,
  apiFetchMediaCatalog,
  navigateToTab,
} from './fixtures';

/**
 * Suite 10 — Skin Enhancer panel (#137, approved composite from #113)
 *
 * Covers:
 *   - #111 decision 5: a per-asset FileManager action opens the panel with that
 *     asset loaded — not a sidebar tab, and images only.
 *   - #111 decision 1: every mode row states its engine (GFPGAN/DiffBIR) and its
 *     per-image budget, and the skin_detail box changes meaning with the mode.
 *   - #113 decisions 1-3: selected vs focused are distinct, an explicit x
 *     deselects a thumb, and one run drives N selected sources.
 *   - Per-item progress on run, and the before/after comparison on completion.
 *
 * The run has two halves because the endpoint is honest about hardware:
 * one test drives the real POST /api/skin-enhance (which answers the labeled
 * degraded envelope on a host with no GPU), and one intercepts that route to
 * exercise the completed → compare path deterministically. The interception is
 * the UI's HTTP seam, not a claimed measurement: no GPU forward pass exists in
 * CI, and inventing one in the product would be the lie this map is avoiding.
 */
test.describe('Skin Enhancer panel', () => {
  const uniqueId = Date.now();
  const firstImage = `e2e-skin-a-${uniqueId}.png`;
  const secondImage = `e2e-skin-b-${uniqueId}.png`;
  const videoFile = `e2e-skin-video-${uniqueId}.mp4`;
  const cleanupPaths: string[] = [firstImage, secondImage, videoFile];

  test.beforeAll(async () => {
    // 1.6x removed the beforeAll(fn, timeout) signature; without a Redis broker
    // each upload burns ~19s in Celery retries, so three of them need the room.
    test.setTimeout(180_000);
    await Promise.all([
      apiUploadFile(firstImage, TEST_FILES.image.buffer, TEST_FILES.image.mime),
      apiUploadFile(secondImage, TEST_FILES.image.buffer, TEST_FILES.image.mime),
      apiUploadFile(videoFile, TEST_FILES.video.buffer, TEST_FILES.video.mime),
    ]);
  });

  test.afterAll(async () => {
    for (const path of cleanupPaths) {
      try { await apiDeleteFile(path); } catch { /* best-effort */ }
    }
  });

  async function openPanel(page: import('@playwright/test').Page, fileName: string) {
    await page.goto('/');
    await navigateToTab(page, 'Media Library');
    await page.waitForTimeout(1500);
    const openButton = page.getByRole('button', { name: `Skin enhance ${fileName}` });
    await expect(openButton).toBeVisible({ timeout: 15000 });
    await openButton.click();
    await expect(page.getByTestId('skin-enhancer-panel')).toBeVisible();
  }

  test('per-asset action opens the panel loaded with that asset; video rows are refused', async ({ page }) => {
    await openPanel(page, firstImage);

    // Loaded with the asset: it is selected, focused, and named on the canvas.
    await expect(page.getByTestId('skin-canvas').getByText(firstImage)).toBeVisible();
    await expect(page.getByText(/1 selected/).first()).toBeVisible();
    await expect(page.getByRole('button', { name: `Remove ${firstImage} from selection` })).toBeVisible();

    // B's contribution: engine + per-image budget on every mode row (#111 decision 1).
    const faithful = page.getByTestId('skin-mode-faithful');
    await expect(faithful).toContainText('GFPGAN');
    await expect(faithful).toContainText('~5s/image');
    const creative = page.getByTestId('skin-mode-creative');
    await expect(creative).toContainText('DiffBIR');
    await expect(creative).toContainText('~60s/image');
    await expect(page.getByTestId('skin-mode-flexible')).toContainText('~60s/image');

    // The honest-knob box names the live meaning of skin_detail and follows the mode.
    await expect(page.getByTestId('skin-detail-meaning')).toContainText('post-filter');
    await page.getByTestId('skin-mode-creative').click();
    await expect(page.getByTestId('skin-detail-meaning')).toContainText('DiffBIR guidance');
    // Flexible exposes the five verbatim Magnific presets.
    await page.getByTestId('skin-mode-flexible').click();
    const presetSelect = page.getByTestId('skin-preset');
    await expect(presetSelect).toBeVisible();
    const presetIds = await presetSelect.locator('option').evaluateAll((opts) =>
      opts.map((o) => (o as HTMLOptionElement).value),
    );
    expect(presetIds).toEqual([
      'enhance_skin',
      'improve_lighting',
      'enhance_everything',
      'transform_to_real',
      'no_make_up',
    ]);
    await page.getByTestId('skin-mode-faithful').click();

    // Images only: the panel is not offered for a video (#111 decision 6).
    await page.getByRole('button', { name: 'Close skin enhancer' }).click();
    await expect(page.getByTestId('skin-enhancer-panel')).not.toBeVisible();
    const videoButton = page.getByRole('button', { name: `Skin enhance ${videoFile}` });
    await expect(videoButton).toBeVisible();
    await expect(videoButton).toBeDisabled();

    // Not a sidebar tab: the enhancer has no entry of its own.
    await expect(page.locator('aside').getByText('Skin Enhancer')).toHaveCount(0);
  });

  test('select two sources, run once, and report per-item progress', async ({ page }) => {
    await openPanel(page, firstImage);

    // Select the second portrait: clicking an unselected thumb selects and focuses it.
    await page.locator(`button:has(img[alt="${secondImage}"])`).click();
    await expect(page.getByText(/2 selected/).first()).toBeVisible();

    // Explicit x deselects — the tap target never changes meaning (#113 decision 3).
    await page.getByRole('button', { name: `Remove ${secondImage} from selection` }).click();
    await expect(page.getByText(/1 selected/).first()).toBeVisible();
    await page.locator(`button:has(img[alt="${secondImage}"])`).click();
    await expect(page.getByText(/2 selected/).first()).toBeVisible();

    // One run drives every selected source (#113 decision 2).
    await page.getByTestId('skin-run').click();

    const terminal = /Enhanced \d+ faces?|degraded|failed/;
    await expect(
      page.locator('[data-testid^="skin-result-"]').filter({ hasText: terminal }),
    ).toHaveCount(2, { timeout: 90_000 });

    // Host capability decides the outcome; both outcomes are surfaced, never hidden.
    // Counted on the tray rows only: the canvas also repeats the focused status.
    const rows = page.locator('[data-testid^="skin-result-"]');
    const degradedRows = await rows.filter({ hasText: 'Local pipeline unavailable' }).count();
    const completedRows = await rows.filter({ hasText: /Enhanced \d+ faces?/ }).count();
    expect(degradedRows + completedRows).toBe(2);
    test.info().annotations.push({
      type: 'run-outcome',
      description: `${completedRows} completed, ${degradedRows} degraded on this host`,
    });

    if (degradedRows > 0) {
      // The amber degraded card is the precedent from GenerationPanel (#111 contract).
      await expect(page.getByText('Local pipeline unavailable').first()).toBeVisible();
    }

    if (completedRows > 0) {
      await expect(page.getByTestId('skin-fullscreen-compare')).toBeEnabled();
      await page.getByTestId('skin-fullscreen-compare').click();
      await expect(page.getByText('Before', { exact: true })).toBeVisible({ timeout: 10000 });
      await expect(page.getByText('Enhanced', { exact: true })).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(page.getByText('Before', { exact: true })).not.toBeVisible();
    } else {
      // Nothing to compare: the button says so instead of opening an empty modal.
      await expect(page.getByTestId('skin-fullscreen-compare')).toBeDisabled();
    }
  });

  test('a completed run reports face progress and opens the before/after compare', async ({ page }) => {
    const catalog = await apiFetchMediaCatalog('', 100);
    const source = catalog.find((a: any) => a.file_path === firstImage);
    expect(source).toBeTruthy();

    await page.route('**/api/skin-enhance', async (route) => {
      const body = route.request().postDataJSON() as { image_path: string };
      // Hold the response long enough to observe the in-flight controls.
      await new Promise((resolve) => setTimeout(resolve, 2500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: {
          status: 'COMPLETED',
          mode: 'flexible',
          preset: 'enhance_skin',
          engine: 'diffbir',
          source_path: body.image_path,
          filename: 'skin_enhanced/stub.png',
          url: source.url,
          faces_enhanced: 2,
          faces_skipped: 0,
          image_size: [1, 1],
          parameters: { sharpen: 40, smart_grain: 20, skin_detail: 80 },
        },
      });
    });

    await openPanel(page, firstImage);
    await page.locator(`button:has(img[alt="${secondImage}"])`).click();
    await expect(page.getByText(/2 selected/).first()).toBeVisible();

    // Flexible mode so the preset select is on screen while the job runs.
    await page.getByTestId('skin-mode-flexible').click();
    await page.getByTestId('skin-run').click();

    // In flight: the row states the engine and the stated per-image budget —
    // no invented percentage, no invented face index (#111 decision 7).
    await expect(page.getByText('Enhancing · DiffBIR · ~60s/image').first()).toBeVisible({
      timeout: 10000,
    });

    // Every control that feeds the in-flight job is locked for its duration, so
    // the rail cannot claim a mode the running request did not use.
    await expect(page.getByTestId('skin-mode-faithful')).toBeDisabled();
    await expect(page.getByTestId('skin-mode-creative')).toBeDisabled();
    await expect(page.getByTestId('skin-mode-flexible')).toBeDisabled();
    await expect(page.getByTestId('skin-preset')).toBeDisabled();
    await expect(page.locator('#skin-slider-sharpen')).toBeDisabled();
    await expect(page.locator('#skin-slider-smartGrain')).toBeDisabled();
    await expect(page.locator('#skin-slider-skinDetail')).toBeDisabled();

    await expect(
      page.locator('[data-testid^="skin-result-"]').filter({ hasText: 'Enhanced 2 faces' }),
    ).toHaveCount(2, { timeout: 30000 });
    await expect(page.getByTestId('skin-canvas').getByText('after')).toBeVisible();

    // The comparison uses the shipped BeforeAfterModal, paired by source_path.
    const compare = page.getByTestId('skin-fullscreen-compare');
    await expect(compare).toBeEnabled();
    await compare.click();
    await expect(page.getByText('Before', { exact: true })).toBeVisible({ timeout: 10000 });
    await expect(page.getByText('Enhanced', { exact: true })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByText('Before', { exact: true })).not.toBeVisible({ timeout: 5000 });

    // Split divider: horizontal slider with keyboard bounds from the ends.
    const split = page.getByTestId('skin-split');
    await expect(split).toHaveAttribute('aria-orientation', 'horizontal');
    await split.focus();
    await page.keyboard.press('End');
    await expect(split).toHaveAttribute('aria-valuenow', '100');
    await page.keyboard.press('Home');
    await expect(split).toHaveAttribute('aria-valuenow', '0');

    // The counter-scaled before layer opts out of preflight's img max-width.
    await expect(page.getByTestId('skin-canvas').locator('img[alt$=" before"]')).toHaveClass(
      /max-w-none/,
    );

    // The tray result thumb describes itself.
    await expect(page.getByRole('img', { name: `${firstImage} result` })).toBeAttached();

    // Every row announces its own status changes: queued → running → final.
    await expect(page.getByTestId('skin-results').getByRole('status')).toHaveCount(2);
  });

  test('a completed response with no output image is reported as a failure', async ({ page }) => {
    // `generate_url` answers "" when it cannot sign the object, and the backend
    // still says COMPLETED. Storing that as a result would show the user a
    // finished run they can never open.
    await page.route('**/api/skin-enhance', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: {
          status: 'COMPLETED',
          mode: 'faithful',
          preset: null,
          engine: 'gfpgan',
          source_path: firstImage,
          filename: 'skin_enhanced/empty.png',
          url: '',
          faces_enhanced: 1,
          faces_skipped: 0,
          image_size: [1, 1],
          parameters: { sharpen: 40, smart_grain: 20, skin_detail: 80 },
        },
      });
    });

    await openPanel(page, firstImage);
    await page.getByTestId('skin-run').click();

    await expect(
      page.locator('[data-testid^="skin-result-"]').filter({ hasText: 'failed' }),
    ).toHaveCount(1, { timeout: 15000 });
    await expect(page.getByText('The enhancer returned no output image.')).toBeVisible();
    await expect(page.getByTestId('skin-fullscreen-compare')).toBeDisabled();
  });

  test('closing the overlay mid-run stops the remaining requests', async ({ page }) => {
    const catalog = await apiFetchMediaCatalog('', 100);
    const source = catalog.find((a: any) => a.file_path === firstImage);
    expect(source).toBeTruthy();

    const posted: string[] = [];
    await page.route('**/api/skin-enhance', async (route) => {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON() as { image_path: string };
        posted.push(body.image_path);
      }
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        json: {
          status: 'COMPLETED',
          mode: 'faithful',
          preset: null,
          engine: 'gfpgan',
          source_path: 'closed.png',
          filename: 'skin_enhanced/closed.png',
          url: source.url,
          faces_enhanced: 1,
          faces_skipped: 0,
          image_size: [1, 1],
          parameters: { sharpen: 40, smart_grain: 20, skin_detail: 80 },
        },
      });
    });

    await openPanel(page, firstImage);
    await page.locator(`button:has(img[alt="${secondImage}"])`).click();
    await expect(page.getByText(/2 selected/).first()).toBeVisible();

    await page.getByTestId('skin-run').click();
    await expect(page.getByText('Enhancing · GFPGAN · ~5s/image').first()).toBeVisible({
      timeout: 10000,
    });
    await expect(posted).toHaveLength(1);

    // Close while the first request is still in flight: the loop must not fire
    // the second request or write results into an unmounted panel.
    await page.getByRole('button', { name: 'Close skin enhancer' }).click();
    await expect(page.getByTestId('skin-enhancer-panel')).not.toBeVisible();

    await page.waitForTimeout(4000);
    expect(posted).toHaveLength(1);
  });
});
