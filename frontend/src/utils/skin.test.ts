import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_SKIN_DETAIL,
  FLEXIBLE_PRESETS,
  INITIAL_SKIN_SETTINGS,
  MODES,
  SLIDER_MAX,
  SLIDER_MIN,
  buildSkinEnhancePayload,
  isSkinEnhanceableImage,
  modeMeta,
  parseSkinFailure,
  resolveSkinDetailMeaning,
  skinItemStatusText,
  validateSkinSlider,
} from './skin';

describe('skin mode table (#111 decision 1)', () => {
  it('ships exactly faithful/creative/flexible in that order', () => {
    assert.deepEqual(
      MODES.map((m) => m.id),
      ['faithful', 'creative', 'flexible'],
    );
  });

  it('maps Faithful to GFPGAN and Creative/Flexible to DiffBIR', () => {
    assert.equal(modeMeta('faithful').engine, 'GFPGAN');
    assert.equal(modeMeta('creative').engine, 'DiffBIR');
    assert.equal(modeMeta('flexible').engine, 'DiffBIR');
  });

  it('states the per-image budget from #111: ~5s Faithful, ~60s otherwise', () => {
    assert.equal(modeMeta('faithful').budget, '~5s');
    assert.equal(modeMeta('creative').budget, '~60s');
    assert.equal(modeMeta('flexible').budget, '~60s');
  });

  it('gives every mode a human blurb', () => {
    for (const mode of MODES) {
      assert.ok(mode.label.length > 0);
      assert.ok(mode.blurb.length > 0);
    }
  });
});

describe('flexible presets (#111 decision 3)', () => {
  it('keeps Magnific optimized_for names verbatim', () => {
    assert.deepEqual(
      FLEXIBLE_PRESETS.map((p) => p.id),
      [
        'enhance_skin',
        'improve_lighting',
        'enhance_everything',
        'transform_to_real',
        'no_make_up',
      ],
    );
  });

  it('displays the raw id and carries a one-line disambiguation', () => {
    for (const preset of FLEXIBLE_PRESETS) {
      assert.equal(preset.label, preset.id);
      assert.ok(preset.blurb.length > 0);
    }
  });
});

describe('skin_detail is a different knob per mode (#111 decision 2)', () => {
  it('defaults to Magnific documented 80', () => {
    assert.equal(DEFAULT_SKIN_DETAIL, 80);
    assert.equal(INITIAL_SKIN_SETTINGS.skinDetail, 80);
  });

  it('is a post-filter in Faithful', () => {
    const meaning = resolveSkinDetailMeaning('faithful');
    assert.equal(meaning.engine, 'post-filter');
    assert.match(meaning.meaning, /texture retention/i);
  });

  it('is DiffBIR guidance in Creative and Flexible', () => {
    for (const mode of ['creative', 'flexible'] as const) {
      const meaning = resolveSkinDetailMeaning(mode);
      assert.equal(meaning.engine, 'DiffBIR guidance');
      assert.match(meaning.meaning, /stylisation|fidelity/i);
    }
  });
});

describe('slider validation mirrors the 400 contract (#111 decision 4)', () => {
  it('accepts the whole 0..100 range, endpoints included', () => {
    assert.equal(validateSkinSlider('sharpen', SLIDER_MIN), null);
    assert.equal(validateSkinSlider('smart_grain', SLIDER_MAX), null);
    assert.equal(validateSkinSlider('skin_detail', 80), null);
  });

  it('refuses out-of-range instead of clamping', () => {
    const err = validateSkinSlider('sharpen', 999);
    assert.ok(err);
    assert.match(err!, /sharpen/);
    assert.match(err!, /out of range/);
    assert.match(err!, /not clamped/);
    assert.match(validateSkinSlider('skin_detail', -1)!, /out of range/);
  });

  it('refuses a fractional value rather than truncating it', () => {
    assert.match(validateSkinSlider('sharpen', 12.5)!, /whole number/);
  });

  it('refuses non-finite values as their own class of error', () => {
    assert.match(validateSkinSlider('smart_grain', Number.NaN)!, /finite/);
    assert.match(validateSkinSlider('smart_grain', Number.POSITIVE_INFINITY)!, /finite/);
  });
});

describe('payload building (#111 decisions 3 and 4)', () => {
  it('sends the approved default sliders verbatim', () => {
    const result = buildSkinEnhancePayload(INITIAL_SKIN_SETTINGS, 'portraits/a.png');
    assert.ok(result.ok);
    assert.equal(result.payload.sharpen, 40);
    assert.equal(result.payload.smart_grain, 20);
    assert.equal(result.payload.skin_detail, 80);
    assert.equal(result.payload.image_path, 'portraits/a.png');
    assert.equal(result.payload.mode, 'faithful');
  });

  it('includes the preset only in flexible mode (the backend 400s otherwise)', () => {
    const flexible = buildSkinEnhancePayload(
      { ...INITIAL_SKIN_SETTINGS, mode: 'flexible', preset: 'no_make_up' },
      'a.png',
    );
    assert.ok(flexible.ok);
    assert.equal(flexible.payload.preset, 'no_make_up');

    const creative = buildSkinEnhancePayload(
      { ...INITIAL_SKIN_SETTINGS, mode: 'creative', preset: 'enhance_skin' },
      'a.png',
    );
    assert.ok(creative.ok);
    assert.equal('preset' in creative.payload, false);

    const faithful = buildSkinEnhancePayload(INITIAL_SKIN_SETTINGS, 'a.png');
    assert.ok(faithful.ok);
    assert.equal('preset' in faithful.payload, false);
  });

  it('defaults flexible to enhance_skin when no preset was chosen', () => {
    const result = buildSkinEnhancePayload(
      { ...INITIAL_SKIN_SETTINGS, mode: 'flexible', preset: '' },
      'a.png',
    );
    assert.ok(result.ok);
    assert.equal(result.payload.preset, 'enhance_skin');
  });

  it('never clamps an out-of-range slider — it refuses the payload', () => {
    const result = buildSkinEnhancePayload(
      { ...INITIAL_SKIN_SETTINGS, sharpen: 999 },
      'a.png',
    );
    assert.equal(result.ok, false);
    assert.equal(result.ok === false && result.field, 'sharpen');
    assert.match(result.ok === false ? result.error : '', /not clamped/);
  });

  it('refuses an empty image path', () => {
    const result = buildSkinEnhancePayload(INITIAL_SKIN_SETTINGS, '   ');
    assert.equal(result.ok, false);
    assert.equal(result.ok === false && result.field, 'image_path');
  });
});

describe('backend refusal slugs surface in human terms (#111 decision 6)', () => {
  it('names a video refusal as images-only', () => {
    const failure = parseSkinFailure(
      'video_input_not_supported: Skin enhancement is images only in v1.',
    );
    assert.equal(failure.slug, 'video_input_not_supported');
    assert.match(failure.human, /images only/i);
  });

  it('names a missing face', () => {
    const failure = parseSkinFailure('no_face_detected: No face was found in the image.');
    assert.equal(failure.slug, 'no_face_detected');
    assert.match(failure.human, /no face/i);
  });

  it('names a missing source', () => {
    const failure = parseSkinFailure("source_not_found: Source image 'a.png' was not found in storage.");
    assert.equal(failure.slug, 'source_not_found');
    assert.match(failure.human, /not found/i);
  });

  it('keeps an unslugged 400 readable as-is', () => {
    const failure = parseSkinFailure("Unsupported skin-enhance mode 'warp'. Supported modes: faithful, creative, flexible.");
    assert.equal(failure.slug, null);
    assert.equal(failure.message, "Unsupported skin-enhance mode 'warp'. Supported modes: faithful, creative, flexible.");
    assert.equal(failure.human, failure.message);
  });

  it('does not treat the first word of a plain sentence as a slug', () => {
    const failure = parseSkinFailure('Invalid image_path: must be a relative catalog key.');
    assert.equal(failure.slug, null);
  });
});

describe('images only gate (#111 decision 6)', () => {
  it('accepts image extensions and refuses video/audio', () => {
    assert.equal(isSkinEnhanceableImage('portrait.PNG'), true);
    assert.equal(isSkinEnhanceableImage('shot.webp'), true);
    assert.equal(isSkinEnhanceableImage('clip.mp4'), false);
    assert.equal(isSkinEnhanceableImage('voice.wav'), false);
  });
});

describe('per-item progress text (per-image budget, #111 decision 7)', () => {
  it('states the engine and budget while an item runs', () => {
    const running = skinItemStatusText({ status: 'running' }, 'faithful');
    assert.match(running, /GFPGAN/);
    assert.match(running, /~5s/);

    const diffbir = skinItemStatusText({ status: 'running' }, 'creative');
    assert.match(diffbir, /DiffBIR/);
    assert.match(diffbir, /~60s/);
  });

  it('reports the face count of a completed item rather than inventing one', () => {
    assert.equal(skinItemStatusText({ status: 'completed', faces: 3 }, 'faithful'), 'Enhanced 3 faces');
    assert.equal(skinItemStatusText({ status: 'completed', faces: 1 }, 'faithful'), 'Enhanced 1 face');
  });

  it('says queued before the request starts', () => {
    assert.equal(skinItemStatusText({ status: 'queued' }, 'faithful'), 'Queued');
  });
});
