import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
  scaleFactorToInt,
  resolveUpscaleParams,
  MAX_BULK_QUEUE,
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
