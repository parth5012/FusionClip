import {
  test,
  expect,
  API_BASE,
  TEST_FILES,
  apiUploadFile,
  apiListFiles,
  apiDeleteFile,
  apiFetchMediaCatalog,
  navigateToTab,
} from './fixtures';
import path from 'path';
import fs from 'fs';
import os from 'os';

/**
 * Suite 9 — Magnific Upscaler Ship Flow (#96)
 *
 * Full journey: upload → upscale from FileManager → result lands in the
 * upscaled/ library prefix → catalog indexes it. Plus the Magnific Upscaler
 * panel: engine presets/categories wired, source picker, bulk queue, and
 * before/after compare on completed results.
 */
test.describe('Magnific Upscaler Ship Flow', () => {
  const uniqueId = Date.now();
  const srcName = `e2e-upscale-${uniqueId}.png`;
  const txtName = `e2e-upscale-note-${uniqueId}.txt`;
  const cleanupPaths: string[] = [];

  test.afterAll(async () => {
    // Best-effort cleanup of source + every output produced under upscaled/
    try {
      const listing = await apiListFiles('upscaled/');
      for (const file of listing.files || []) {
        if (file.name.includes(String(uniqueId)) || file.name.includes('e2e-upscale')) {
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

  test('engine exposes preset and category registries', async ({ request }) => {
    const pRes = await request.get(`${API_BASE}/api/upscale/presets`);
    expect(pRes.ok()).toBeTruthy();
    const presets = (await pRes.json()).presets;
    expect(Object.keys(presets)).toEqual(
      expect.arrayContaining(['subtle', 'vivid', 'wild', 'custom']),
    );
    expect(presets.subtle.creativity).toBe(-4);

    const cRes = await request.get(`${API_BASE}/api/upscale/categories`);
    expect(cRes.ok()).toBeTruthy();
    const cats = (await cRes.json()).categories;
    expect(Object.keys(cats)).toEqual(
      expect.arrayContaining(['universal', 'portraits', 'landscapes', 'anime', 'architecture', 'product']),
    );
    expect(cats.portraits.prompt_keywords).toBeTruthy();
  });

  test('upload → FileManager upscale → result lands in library', async ({ page }) => {
    test.setTimeout(120_000);

    /* ── Upload source image via UI ── */
    await page.goto('/');
    await navigateToTab(page, 'Media Library');
    await expect(page.getByText('Local S3 Filemanager')).toBeVisible({ timeout: 15000 });

    const tmp = path.join(os.tmpdir(), srcName);
    fs.writeFileSync(tmp, TEST_FILES.image.buffer);
    await page.locator('input[type="file"]').setInputFiles(tmp);
    // title= locator: name and path render as sibling <p> nodes, so getByText would be ambiguous
    await expect(page.locator(`p[title="${srcName}"]`)).toBeVisible({ timeout: 20000 });
    fs.unlinkSync(tmp);
    cleanupPaths.push(srcName);

    /* ── Non-image files keep the upscale action disabled ── */
    await apiUploadFile(txtName, Buffer.from('not an image'), 'text/plain');
    cleanupPaths.push(txtName);
    await page.locator('button[title="Refresh current folder"]').click();
    const txtBtn = page.getByRole('button', { name: `Upscale ${txtName}` });
    await expect(txtBtn).toBeDisabled({ timeout: 10000 });

    /* ── Open the upscale modal for the image and dispatch ── */
    const imgBtn = page.getByRole('button', { name: `Upscale ${srcName}` });
    await expect(imgBtn).toBeEnabled();
    await imgBtn.click();

    const modal = page.getByTestId('upscale-modal');
    await expect(modal).toBeVisible();
    await page.getByTestId('upscale-scale-2').click();
    await page.getByTestId('upscale-preset-subtle').click();
    await page.getByTestId('upscale-start').click();
    await expect(modal).not.toBeVisible();

    /* ── Job panel shows the running upscale ── */
    await expect(page.getByText('Magnific Upscale Jobs')).toBeVisible({ timeout: 10000 });

    /* ── Poll storage until the output lands under upscaled/ ── */
    const stem = srcName.replace(/\.png$/, '');
    let output: any = null;
    const deadline = Date.now() + 60_000;
    while (Date.now() < deadline && !output) {
      const listing = await apiListFiles('upscaled/');
      output = (listing.files || []).find((f: any) => f.name.startsWith(stem));
      if (!output) await new Promise((r) => setTimeout(r, 1000));
    }
    expect(output, 'upscaled output should land in upscaled/').toBeTruthy();
    cleanupPaths.push(output.path);

    /* ── UI reports COMPLETED with a result link ── */
    await expect(page.getByText('COMPLETED').first()).toBeVisible({ timeout: 30000 });

    /* ── Browse into upscaled/ and see the file (library flow) ── */
    await page.getByRole('button', { name: 'Root' }).click();
    const dirRow = page.locator('span', { hasText: /^upscaled$/ }).first();
    await expect(dirRow).toBeVisible({ timeout: 10000 });
    await dirRow.click();
    await expect(page.locator(`p[title="${output.name}"]`)).toBeVisible({ timeout: 10000 });

    /* ── Catalog indexes the result as a MediaAsset ── */
    const catalog = await apiFetchMediaCatalog();
    const asset = catalog.find((a: any) => a.file_path === output.path);
    expect(asset).toBeTruthy();
    expect(asset.content_type).toBe('image/png');
  });

  test('Magnific panel wires presets, source picker, bulk queue and compare', async ({ page }) => {
    test.setTimeout(120_000);

    /* Self-seed so this test does not depend on test 2's upload having run */
    const panelSrc = `e2e-upscale-panel-${uniqueId}.png`;
    await apiUploadFile(panelSrc, TEST_FILES.image.buffer, 'image/png');
    cleanupPaths.push(panelSrc);

    await page.goto('/');
    await navigateToTab(page, 'Magnific Upscaler');
    await expect(page.getByText('Magnific Generative Upscaler')).toBeVisible({ timeout: 15000 });

    /* ── Preset registry buttons rendered (engine-wired) ── */
    for (const p of ['subtle', 'vivid', 'wild', 'custom']) {
      await expect(page.getByTestId(`variant-preset-${p}`)).toBeVisible();
    }

    /* ── Source picker lists the uploaded image ── */
    const select = page.getByTestId('upscale-source-select');
    await expect(select).toBeVisible();
    // <option> nodes inside a closed <select> are never "visible" to Playwright —
    // assert presence via count/text, then selectOption (which auto-waits too).
    await expect(select.locator('option', { hasText: panelSrc })).toHaveCount(1, { timeout: 15000 });
    await select.selectOption({ label: panelSrc });

    /* ── Queue it for bulk, then dispatch ── */
    await page.getByTestId('upscale-queue-add').click();
    await expect(page.getByText(/Upscale Queue \(1\//)).toBeVisible();

    await page.getByTestId('upscale-start-bulk').click();

    /* ── Job completes → Compare action appears ── */
    await expect(page.getByTitle('Open in compare view')).toBeVisible({ timeout: 60000 });

    /* ── Before/after compare renders with real result URL labels ── */
    await page.getByTitle('Open in compare view').click();
    await expect(page.getByText(/Original 1x/)).toBeVisible({ timeout: 10000 });
    await expect(page.getByText(/Upscaled 4x • SDXL-Tile/)).toBeVisible();
  });
});
