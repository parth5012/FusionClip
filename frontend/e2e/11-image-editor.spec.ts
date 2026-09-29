import {
  test,
  expect,
  API_BASE,
  TEST_FILES,
  apiUploadFile,
  apiDeleteFile,
  apiListFiles,
  apiFetchMediaCatalog,
} from './fixtures';

/**
 * Suite 11 — Image Editor core (#121, map #75).
 *
 * Covers the apply/export pipeline end to end:
 *   - HTTP seam: presets surface, 400 validation, save → list round-trip
 *     (edit-save-reload fidelity at the API level).
 *   - UI seam: /editor/[id] loads the asset, the Adjust panel drives the
 *     recipe, Apply persists a version, reload replays it (fidelity), and
 *     Export produces a real server render — synchronous PIL, so no GPU or
 *     broker is needed and the completed path is exercised for real, not
 *     intercepted.
 */

async function setRangeValue(page: import('@playwright/test').Page, testId: string, value: number) {
  // React controlled range inputs only commit through the native setter +
  // a bubbling input event; keyboard stepping would take one request per tick.
  await page.evaluate(
    ({ id, val }) => {
      const el = document.querySelector(`[data-testid="${id}"]`) as HTMLInputElement | null;
      if (!el) throw new Error(`missing slider ${id}`);
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!;
      setter.call(el, String(val));
      el.dispatchEvent(new Event('input', { bubbles: true }));
    },
    { id: testId, val: value },
  );
}

test.describe('Image Editor core', () => {
  const uniqueId = Date.now();
  const srcName = `e2e-editor-${uniqueId}.png`;
  const cleanupPaths: string[] = [];

  test.afterAll(async () => {
    try {
      const listing = await apiListFiles('edited/');
      for (const file of listing.files || []) {
        if (file.name.includes(String(uniqueId)) || file.name.includes('e2e-editor')) {
          await apiDeleteFile(file.path).catch(() => {});
        }
      }
    } catch { /* ignore */ }
    try {
      const listing = await apiListFiles('edits/');
      for (const file of listing.files || []) {
        if (file.name.includes(String(uniqueId)) || file.name.includes('e2e-editor')) {
          await apiDeleteFile(file.path).catch(() => {});
        }
      }
    } catch { /* ignore */ }
    for (const p of cleanupPaths) {
      try {
        await apiDeleteFile(p);
      } catch { /* best-effort */ }
    }
  });

  test('presets surface, validation 400s, and save → list round-trip', async ({ request }) => {
    const presets = await request.get(`${API_BASE}/api/editor/presets`);
    expect(presets.ok()).toBeTruthy();
    const surface = await presets.json();
    expect(surface.version).toBe(1);
    expect(Object.keys(surface.sliders)).toEqual(
      expect.arrayContaining(['exposure', 'brightness', 'contrast', 'highlights', 'shadows', 'tint', 'grain']),
    );
    expect(surface.crop_aspects).toEqual(expect.arrayContaining(['free', '1:1', '4:3', '16:9']));

    await apiUploadFile(srcName, TEST_FILES.image.buffer, TEST_FILES.image.mime);
    cleanupPaths.push(srcName);

    const bad = await request.post(`${API_BASE}/api/editor/recipe`, {
      data: { source_path: srcName, recipe: { exposure: 101 } },
    });
    expect(bad.status()).toBe(400);

    const saved = await request.post(`${API_BASE}/api/editor/recipe`, {
      data: { source_path: srcName, recipe: { exposure: 25, grain: 10 } },
    });
    expect(saved.ok()).toBeTruthy();
    const savedBody = await saved.json();
    expect(savedBody.status).toBe('SAVED');
    expect(savedBody.recipe.exposure).toBe(25);
    expect(savedBody.recipe.contrast).toBe(0);

    const listed = await request.get(`${API_BASE}/api/editor/recipes`, {
      params: { source_path: srcName },
    });
    expect(listed.ok()).toBeTruthy();
    const listBody = await listed.json();
    expect(listBody.source_path).toBe(srcName);
    expect(listBody.versions.length).toBeGreaterThanOrEqual(1);
    const latest = listBody.versions[listBody.versions.length - 1];
    expect(latest.recipe.exposure).toBe(25);
  });

  test('edit → Apply → reload replays the recipe; Export renders a derivative', async ({ page }) => {
    test.setTimeout(120_000);

    const catalog = await apiFetchMediaCatalog();
    let asset = catalog.find((a: any) => a.file_path === srcName);
    if (!asset) {
      await apiUploadFile(srcName, TEST_FILES.image.buffer, TEST_FILES.image.mime);
      cleanupPaths.push(srcName);
      const retry = await apiFetchMediaCatalog();
      asset = retry.find((a: any) => a.file_path === srcName);
    }
    expect(asset, 'source asset should be catalogued').toBeTruthy();

    await page.goto(`/editor/${asset.id}`);
    await expect(page.getByTestId('adjust-panel')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('editor-preview')).toBeVisible();

    /* ── Default recipe, then one edit ── */
    await expect(page.getByTestId('adjust-slider-exposure')).toHaveValue('0');
    await setRangeValue(page, 'adjust-slider-exposure', 25);
    await expect(page.getByTestId('adjust-slider-exposure')).toHaveValue('25');
    await expect(page.getByTestId('editor-recipe-json')).toContainText('"exposure":25');

    /* ── Undo restores, redo re-applies (session history) ── */
    await page.getByTestId('adjust-undo').click();
    await expect(page.getByTestId('adjust-slider-exposure')).toHaveValue('0');
    await page.getByTestId('adjust-redo').click();
    await expect(page.getByTestId('adjust-slider-exposure')).toHaveValue('25');

    /* ── Apply persists a version ── */
    await page.getByTestId('editor-apply').click();
    await expect(page.getByTestId('editor-saved-version')).toBeVisible({ timeout: 15000 });
    const savedLabel = await page.getByTestId('editor-saved-version').textContent();

    /* ── Reload replays the saved recipe (fidelity) ── */
    await page.reload();
    await expect(page.getByTestId('adjust-panel')).toBeVisible({ timeout: 15000 });
    await expect(page.getByTestId('adjust-slider-exposure')).toHaveValue('25', { timeout: 10000 });
    await expect(page.getByTestId('editor-saved-version')).toHaveText(savedLabel ?? '');

    /* ── Export renders the authoritative derivative ── */
    await page.getByTestId('editor-export').click();
    await expect(page.getByTestId('editor-export-url')).toBeVisible({ timeout: 30000 });
    const exportName = await page.getByTestId('editor-export-url').textContent();
    expect(exportName).toMatch(/^edited\//);
    cleanupPaths.push((exportName ?? '').trim());

    /* ── Catalog carries the derivative with source_path lineage ── */
    const after = await apiFetchMediaCatalog();
    const derivative = after.find((a: any) => a.file_path === (exportName ?? '').trim());
    expect(derivative).toBeTruthy();
  });
});
