import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
  scaleFactorToInt,
  resolveUpscaleParams,
  MAX_BULK_QUEUE,
  PRECISION_PRESETS,
  resolvePrecisionPreset,
  clampPrecisionPct,
  getPrecisionStages,
  formatRungStages,
  formatRungOutputPx,
  computeRungDimensions,
  buildUpscalePayload,
  PRECISION_ENGINES,
  DEFAULT_SOURCE_WIDTH,
  DEFAULT_SOURCE_HEIGHT,
} from './upscale';

describe('upscale slider mapping parity with backend (#96)', () => {
  it('maps creativity to denoise with piecewise center at 0.35', () => {
    assert.equal(mapCreativityToDenoise(-10), 0.1);
    assert.equal(mapCreativityToDenoise(0), 0.35);
    assert.equal(mapCreativityToDenoise(10), 0.65);
  });

  it('clamps creativity outside -10..+10', () => {
    assert.equal(mapCreativityToDenoise(-99), 0.1);
    assert.equal(mapCreativityToDenoise(99), 0.65);
  });

  it('maps resemblance to ControlNet weight with center at 0.85', () => {
    assert.equal(mapResemblanceToControlNet(-10), 0.4);
    assert.equal(mapResemblanceToControlNet(0), 0.85);
    assert.equal(mapResemblanceToControlNet(10), 1.2);
  });

  it('clamps resemblance outside -10..+10', () => {
    assert.equal(mapResemblanceToControlNet(-99), 0.4);
    assert.equal(mapResemblanceToControlNet(99), 1.2);
  });
});

describe('upscale request helpers (#96)', () => {
  it('parses scale factors for the API payload', () => {
    assert.equal(scaleFactorToInt('2x'), 2);
    assert.equal(scaleFactorToInt('4x'), 4);
    assert.equal(scaleFactorToInt('8x'), 8);
    assert.equal(scaleFactorToInt('16x'), 16);
  });

  it('merges explicit slider overrides over preset defaults', () => {
    const params = resolveUpscaleParams('subtle', {
      creativity: 5,
      category: 'anime',
      prompt: 'crisp lines',
    });
    assert.equal(params.preset, 'subtle');
    assert.equal(params.creativity, 5);
    assert.equal(params.resemblance, 7); // subtle default preserved
    assert.equal(params.fractality, -2);
    assert.equal(params.hdr, 1);
    assert.equal(params.category, 'anime');
    assert.equal(params.prompt, 'crisp lines');
  });

  it('caps bulk queue size', () => {
    assert.ok(MAX_BULK_QUEUE >= 4);
    assert.ok(MAX_BULK_QUEUE <= 32);
  });
});

describe('precision mode preset recipes and custom detection (#142)', () => {
  it('defines clean as 15 sharpness and 0 grain', () => {
    assert.equal(PRECISION_PRESETS.clean.sharpness, 15);
    assert.equal(PRECISION_PRESETS.clean.grain, 0);
  });

  it('defines filmic as 40 sharpness and 25 grain', () => {
    assert.equal(PRECISION_PRESETS.filmic.sharpness, 40);
    assert.equal(PRECISION_PRESETS.filmic.grain, 25);
  });

  it('resolves clean and filmic presets from exact sharpness/grain pairs', () => {
    assert.equal(resolvePrecisionPreset(15, 0), 'clean');
    assert.equal(resolvePrecisionPreset(40, 25), 'filmic');
  });

  it('detects custom preset when values deviate from recipes', () => {
    assert.equal(resolvePrecisionPreset(15, 1), 'custom');
    assert.equal(resolvePrecisionPreset(14, 0), 'custom');
    assert.equal(resolvePrecisionPreset(0, 0), 'custom');
    assert.equal(resolvePrecisionPreset(50, 50), 'custom');
  });

  it('clamps precision percentage inputs to integer 0..100', () => {
    assert.equal(clampPrecisionPct(-5), 0);
    assert.equal(clampPrecisionPct(105), 100);
    assert.equal(clampPrecisionPct(15.4), 15);
    assert.equal(clampPrecisionPct(15.6), 16);
  });
});

describe('scale rung and stage math (#142)', () => {
  it('computes progressive 2x chain stage counts', () => {
    assert.equal(getPrecisionStages('2x'), 1);
    assert.equal(getPrecisionStages('4x'), 2);
    assert.equal(getPrecisionStages('8x'), 3);
    assert.equal(getPrecisionStages('16x'), 4);
    assert.equal(getPrecisionStages(2), 1);
    assert.equal(getPrecisionStages(16), 4);
  });

  it('formats rung stage captions with singular/plural stage', () => {
    assert.equal(formatRungStages('2x'), '1 × 2x stage');
    assert.equal(formatRungStages('4x'), '2 × 2x stages');
    assert.equal(formatRungStages('8x'), '3 × 2x stages');
    assert.equal(formatRungStages('16x'), '4 × 2x stages');
  });

  it('computes output pixel dimensions based on source dimensions', () => {
    assert.equal(formatRungOutputPx('2x', 1024, 768), '2048×1536');
    assert.equal(formatRungOutputPx('4x', 1024, 768), '4096×3072');
    assert.equal(formatRungOutputPx('8x', 1024, 768), '8192×6144');
    assert.equal(formatRungOutputPx('16x', 1024, 768), '16384×12288');
    assert.equal(formatRungOutputPx('4x'), `${DEFAULT_SOURCE_WIDTH * 4}×${DEFAULT_SOURCE_HEIGHT * 4}`);
  });

  it('calculates numerical rung dimensions object', () => {
    const dims = computeRungDimensions('4x', 800, 600);
    assert.deepEqual(dims, { width: 3200, height: 2400 });
  });

  it('defines HAT and SCUNet engines with hint copy and vram specs', () => {
    const hat = PRECISION_ENGINES.find((e) => e.id === 'hat');
    const scunet = PRECISION_ENGINES.find((e) => e.id === 'scunet');
    assert.ok(hat);
    assert.ok(scunet);
    assert.match(hat.hint, /Clean sources/i);
    assert.match(hat.vram, /2\.3/);
    assert.match(scunet.hint, /Noisy/i);
    assert.match(scunet.vram, /2\.1/);
  });
});

describe('POST /api/upscale payload builder (#142, #123-d11)', () => {
  it('builds precision mode payload with precision fields and omits creative fields', () => {
    const payload = buildUpscalePayload({
      image_path: 'inputs/photo.png',
      scale: '4x',
      mode: 'precision',
      engine: 'hat',
      sharpness: 15,
      grain: 0,
    });

    assert.equal(payload.image_path, 'inputs/photo.png');
    assert.equal(payload.scale, 4);
    assert.equal(payload.mode, 'precision');
    assert.equal(payload.engine, 'hat');
    assert.equal(payload.sharpness, 15);
    assert.equal(payload.grain, 0);

    // Backend 422s if creative controls are present on precision mode (#123-d8)
    assert.equal('creativity' in payload, false, 'creativity must be omitted in precision mode');
    assert.equal('resemblance' in payload, false, 'resemblance must be omitted in precision mode');
    assert.equal('fractality' in payload, false, 'fractality must be omitted in precision mode');
    assert.equal('hdr' in payload, false, 'hdr must be omitted in precision mode');
    assert.equal('preset' in payload, false, 'creative preset must be omitted in precision mode');
    assert.equal('category' in payload, false, 'category must be omitted in precision mode');
    assert.equal('prompt' in payload, false, 'prompt must be omitted in precision mode');

    const json = JSON.stringify(payload);
    assert.equal(json.includes('creativity'), false);
    assert.equal(json.includes('resemblance'), false);
    assert.equal(json.includes('fractality'), false);
    assert.equal(json.includes('hdr'), false);
  });

  it('builds creative mode payload with creative sliders and omits precision fields', () => {
    const payload = buildUpscalePayload({
      image_path: 'inputs/art.png',
      scale: '2x',
      mode: 'creative',
      preset: 'subtle',
      category: 'anime',
      creativity: -4,
      resemblance: 7,
      fractality: -2,
      hdr: 1,
      prompt: 'sharp linework',
    });

    assert.equal(payload.image_path, 'inputs/art.png');
    assert.equal(payload.scale, 2);
    assert.equal(payload.mode, 'creative');
    assert.equal(payload.preset, 'subtle');
    assert.equal(payload.category, 'anime');
    assert.equal(payload.creativity, -4);
    assert.equal(payload.resemblance, 7);
    assert.equal(payload.fractality, -2);
    assert.equal(payload.hdr, 1);
    assert.equal(payload.prompt, 'sharp linework');

    // Backend 422s if precision controls are present on creative mode (#123-d11)
    assert.equal('engine' in payload, false, 'engine must be omitted in creative mode');
    assert.equal('sharpness' in payload, false, 'sharpness must be omitted in creative mode');
    assert.equal('grain' in payload, false, 'grain must be omitted in creative mode');

    const json = JSON.stringify(payload);
    assert.equal(json.includes('engine'), false);
    assert.equal(json.includes('sharpness'), false);
    assert.equal(json.includes('grain'), false);
  });

  it('defaults mode to creative when omitted and fills preset defaults', () => {
    const payload = buildUpscalePayload({
      image_path: 'inputs/default.png',
      scale: '4x',
      preset: 'wild',
    });

    assert.equal(payload.mode, 'creative');
    assert.equal(payload.scale, 4);
    assert.equal(payload.preset, 'wild');
    assert.equal(payload.creativity, 7);
    assert.equal(payload.resemblance, -2);
    assert.equal(payload.fractality, 6);
    assert.equal(payload.hdr, 4);
    assert.equal('engine' in payload, false);
    assert.equal('sharpness' in payload, false);
    assert.equal('grain' in payload, false);
  });

  it('clamps precision sliders to 0..100 in buildUpscalePayload', () => {
    const payload = buildUpscalePayload({
      image_path: 'inputs/clamped.png',
      scale: '8x',
      mode: 'precision',
      engine: 'scunet',
      sharpness: 120,
      grain: -10,
    });

    assert.equal(payload.sharpness, 100);
    assert.equal(payload.grain, 0);
  });
});
