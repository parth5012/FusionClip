import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  CROP_ASPECTS,
  DEFAULT_RECIPE,
  RECIPE_VERSION,
  ROTATE_RANGE,
  SLIDERS,
  canonicalRecipe,
  isDefaultRecipe,
  recipeFingerprint,
  recipeToFfmpegFilter,
  recipeToFilter,
  validateRecipe,
} from './editor';

describe('editor recipe contract (#121)', () => {
  it('pins the versioned default recipe (7 ops + rotate + crop)', () => {
    assert.equal(RECIPE_VERSION, 1);
    assert.deepEqual(DEFAULT_RECIPE, {
      exposure: 0,
      brightness: 0,
      contrast: 0,
      highlights: 0,
      shadows: 0,
      tint: 0,
      grain: 0,
      rotate: 0,
      cropAspect: 'free',
    });
    assert.equal(SLIDERS.length, 7);
    assert.deepEqual(
      SLIDERS.map((s) => s.key),
      ['exposure', 'brightness', 'contrast', 'highlights', 'shadows', 'tint', 'grain'],
    );
    assert.deepEqual(ROTATE_RANGE, { min: -45, max: 45, default: 0 });
    assert.deepEqual([...CROP_ASPECTS], ['free', '1:1', '4:3', '16:9']);
  });

  it('fills missing keys with defaults and refuses unknown keys', () => {
    const filled = validateRecipe({ exposure: 25 });
    assert.equal(filled.ok, true);
    if (filled.ok) {
      assert.equal(filled.recipe.exposure, 25);
      assert.equal(filled.recipe.contrast, 0);
      assert.equal(filled.recipe.cropAspect, 'free');
    }
    const unknown = validateRecipe({ vibrance: 10 } as never);
    assert.equal(unknown.ok, false);
    if (!unknown.ok) assert.match(unknown.error, /Unknown recipe key/);
  });

  it('refuses out-of-range, fractional and bad enum values with the field name', () => {
    for (const bad of [
      { exposure: 101 },
      { grain: -1 },
      { contrast: 12.5 },
      { rotate: 90 },
      { cropAspect: '3:2' },
    ]) {
      const res = validateRecipe(bad as never);
      assert.equal(res.ok, false, JSON.stringify(bad));
      if (!res.ok) assert.ok(res.error.length > 0);
    }
    const out = validateRecipe({ exposure: 101 });
    assert.equal(out.ok, false);
    if (!out.ok) assert.match(out.error, /exposure/);
  });

  it('maps the default recipe to an identity CSS preview filter', () => {
    const filter = recipeToFilter(DEFAULT_RECIPE);
    assert.match(filter, /brightness\(1\.000\)/);
    assert.match(filter, /contrast\(1\.000\)/);
    const pushed = recipeToFilter({ ...DEFAULT_RECIPE, exposure: 100 });
    assert.ok(pushed !== filter);
    assert.match(pushed, /brightness\(1\.500\)/);
  });

  it('maps recipes to the ffmpeg filter the future Celery worker consumes', () => {
    const base = recipeToFfmpegFilter(DEFAULT_RECIPE);
    assert.match(base, /^eq=brightness=0\.0000:contrast=1\.0000:saturation=1\.0000$/);
    assert.ok(!base.includes('noise='));
    const grainy = recipeToFfmpegFilter({ ...DEFAULT_RECIPE, grain: 40 });
    assert.match(grainy, /noise=alls=10:allf=t/);
  });

  it('canonical form is key-order stable and the fingerprint is deterministic', () => {
    // Same values, different insertion order (a spread would overwrite tint).
    const reordered = {
      tint: 5,
      exposure: 0,
      brightness: 0,
      contrast: 0,
      highlights: 0,
      shadows: 0,
      grain: 0,
      rotate: 0,
      cropAspect: 'free',
    } as const;
    const a = canonicalRecipe({ ...DEFAULT_RECIPE, tint: 5 });
    const b = canonicalRecipe({ ...reordered });
    assert.equal(a, b);
    assert.equal(recipeFingerprint({ ...DEFAULT_RECIPE, tint: 5 }), recipeFingerprint({ ...reordered }));
    assert.notEqual(recipeFingerprint(DEFAULT_RECIPE), recipeFingerprint({ ...DEFAULT_RECIPE, tint: 5 }));
  });

  it('detects the default recipe', () => {
    assert.equal(isDefaultRecipe(DEFAULT_RECIPE), true);
    assert.equal(isDefaultRecipe({ ...DEFAULT_RECIPE, shadows: 1 }), false);
  });
});
