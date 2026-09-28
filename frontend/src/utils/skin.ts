/**
 * Skin Enhancer contract (#111, panel #137).
 *
 * The frontend copy of the decisions locked in the #111 grilling and described
 * by the prototype's `types.ts`: the mode/engine/budget table, the five verbatim
 * Magnific presets, the mode-aware meaning of `skin_detail`, and the 0..100
 * slider rule (out-of-range is refused, never clamped — the backend answers 400
 * for the same value, so clamping here would only hide it).
 *
 * `GET /api/skin-enhance/presets` remains the source of truth for what the
 * endpoint validates; these helpers are what the panel renders and builds when
 * that read is unavailable, and they are assertable without a GPU.
 */
import { isImageFile } from './upscale';

export type SkinMode = 'faithful' | 'creative' | 'flexible';

export interface SkinModeMeta {
  id: SkinMode;
  label: string;
  /** Engine that runs this mode — #111 decision 1. */
  engine: string;
  /** Stated per-image budget from #111 decision 7 (an estimate, never a measurement). */
  budget: string;
  blurb: string;
}

/** #111 decision 1: GFPGAN for Faithful, DiffBIR for Creative and Flexible. */
export const MODES: SkinModeMeta[] = [
  {
    id: 'faithful',
    label: 'Faithful',
    engine: 'GFPGAN',
    budget: '~5s',
    blurb: 'Preserve identity. Natural improvement only.',
  },
  {
    id: 'creative',
    label: 'Creative',
    engine: 'DiffBIR',
    budget: '~60s',
    blurb: 'Most stylised reinterpretation. May alter facial geometry.',
  },
  {
    id: 'flexible',
    label: 'Flexible',
    engine: 'DiffBIR',
    budget: '~60s',
    blurb: 'Targeted fix driven by a preset.',
  },
];

export function modeMeta(mode: SkinMode): SkinModeMeta {
  return MODES.find((m) => m.id === mode) ?? MODES[0];
}

export interface SkinPresetMeta {
  id: string;
  label: string;
  blurb: string;
}

/** Verbatim Magnific `optimized_for` values — #111 decision 3, no renaming. */
export const FLEXIBLE_PRESETS: SkinPresetMeta[] = [
  { id: 'enhance_skin', label: 'enhance_skin', blurb: 'The default. Clean up and even out tone.' },
  { id: 'improve_lighting', label: 'improve_lighting', blurb: 'Lift flat or uneven lighting on the face.' },
  { id: 'enhance_everything', label: 'enhance_everything', blurb: 'Whole-image lift, not just skin.' },
  { id: 'transform_to_real', label: 'transform_to_real', blurb: 'Push a stylised render toward photoreal.' },
  { id: 'no_make_up', label: 'no_make_up', blurb: 'Reduce visible cosmetics rather than enhance them.' },
];

export const DEFAULT_FLEXIBLE_PRESET = 'enhance_skin';

export const SLIDER_MIN = 0;
export const SLIDER_MAX = 100;
/** Magnific's documented default (#111 decision 4). */
export const DEFAULT_SKIN_DETAIL = 80;

export type SkinSliderKey = 'sharpen' | 'smart_grain' | 'skin_detail';

export interface SkinSettings {
  mode: SkinMode;
  preset: string;
  sharpen: number;
  smartGrain: number;
  skinDetail: number;
}

/** Initial values of the approved composite's control rail. */
export const INITIAL_SKIN_SETTINGS: SkinSettings = {
  mode: 'faithful',
  preset: DEFAULT_FLEXIBLE_PRESET,
  sharpen: 40,
  smartGrain: 20,
  skinDetail: DEFAULT_SKIN_DETAIL,
};

/**
 * #111 decision 2: `skin_detail` is not the same physical knob per mode.
 * GFPGAN exposes no such control, so Faithful substitutes a post-filter; DiffBIR
 * exposes a guidance scale. Any label that does not say which one is live lies.
 */
export function resolveSkinDetailMeaning(mode: SkinMode): { engine: string; meaning: string } {
  return mode === 'faithful'
    ? { engine: 'post-filter', meaning: 'texture retention after restore' }
    : { engine: 'DiffBIR guidance', meaning: 'fidelity vs. stylisation' };
}

/**
 * Range/integrality check for one slider, mirroring the backend's 400 text.
 *
 * Returns `null` when the value may be sent, otherwise the message the panel
 * shows. Clamping is deliberately absent: a silently clamped `sharpen=999`
 * produces output the user cannot explain (#111 decision 4).
 */
export function validateSkinSlider(name: SkinSliderKey, value: number): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return (
      `Slider '${name}' value ${value} must be a finite whole number: the ` +
      `wire format is an integer ${SLIDER_MIN}..${SLIDER_MAX} range.`
    );
  }
  if (!Number.isInteger(value)) {
    return (
      `Slider '${name}' value ${value} must be a whole number: the wire format ` +
      `is an integer ${SLIDER_MIN}..${SLIDER_MAX} range.`
    );
  }
  if (value < SLIDER_MIN || value > SLIDER_MAX) {
    return (
      `Slider '${name}' value ${value} is out of range: must be between ` +
      `${SLIDER_MIN} and ${SLIDER_MAX}. Values are not clamped.`
    );
  }
  return null;
}

export interface SkinEnhancePayload {
  image_path: string;
  mode: SkinMode;
  preset?: string;
  sharpen: number;
  smart_grain: number;
  skin_detail: number;
}

export type SkinPayloadResult =
  | { ok: true; payload: SkinEnhancePayload }
  | { ok: false; field: string; error: string };

/**
 * Build the POST /api/skin-enhance body, or refuse to.
 *
 * `preset` is sent only in flexible mode: the endpoint answers 400 when a
 * preset rides along with another mode rather than dropping it, so dropping it
 * here would hide a real contract rule from whoever wired the call.
 */
export function buildSkinEnhancePayload(
  settings: SkinSettings,
  imagePath: string,
): SkinPayloadResult {
  const path = (imagePath ?? '').trim();
  if (!path) {
    return { ok: false, field: 'image_path', error: 'No source image selected.' };
  }

  const sliders: Array<[SkinSliderKey, number]> = [
    ['sharpen', settings.sharpen],
    ['smart_grain', settings.smartGrain],
    ['skin_detail', settings.skinDetail],
  ];
  for (const [name, value] of sliders) {
    const error = validateSkinSlider(name, value);
    if (error) return { ok: false, field: name, error };
  }

  const payload: SkinEnhancePayload = {
    image_path: path,
    mode: settings.mode,
    sharpen: settings.sharpen,
    smart_grain: settings.smartGrain,
    skin_detail: settings.skinDetail,
  };
  if (settings.mode === 'flexible') {
    payload.preset = settings.preset?.trim() || DEFAULT_FLEXIBLE_PRESET;
  }
  return { ok: true, payload };
}

/** Machine-readable reason slug a 400 detail may carry, plus readable text. */
export interface SkinFailure {
  slug: string | null;
  message: string;
  human: string;
}

/** Slugs the endpoint can answer with, mapped to what a user should read (#111 decision 6). */
const SLUG_HUMAN: Record<string, string> = {
  video_input_not_supported: 'Video input is not supported — Skin Enhancer runs on images only.',
  no_face_detected: 'No face was found in this image, and only detected faces can be restored.',
  source_not_found: 'The source image was not found in storage.',
};

/**
 * Split a backend 400 `detail` into its reason slug and a human sentence.
 *
 * Slugs are `snake_case:`-prefixed (`video_input_not_supported: ...`). A plain
 * sentence must not be misread as a slug, so only a leading snake_case token
 * followed by ': ' counts — `Invalid image_path: ...` stays unslugged.
 */
export function parseSkinFailure(detail: string): SkinFailure {
  const message = (detail ?? '').trim();
  const match = /^([a-z][a-z0-9]*(?:_[a-z0-9]+)+):\s*([\s\S]*)$/.exec(message);
  if (!match) {
    return { slug: null, message, human: message };
  }
  const slug = match[1];
  const rest = match[2].trim() || message;
  return {
    slug,
    message: rest,
    human: SLUG_HUMAN[slug] ?? rest,
  };
}

/** True when the storage object is an image this panel may point at. */
export function isSkinEnhanceableImage(name: string): boolean {
  return isImageFile(name);
}

export type SkinItemStatus = 'queued' | 'running' | 'completed' | 'degraded' | 'failed';

export interface SkinItemProgress {
  status: SkinItemStatus;
  faces?: number;
}

/**
 * Per-item progress line for the results tray.
 *
 * The endpoint is synchronous and reports no intermediate progress, so the only
 * honest states are "not started", "in flight — with the engine and the stated
 * per-image budget", and "done — with the face count the run actually
 * reported". No percentage and no face index is invented.
 */
export function skinItemStatusText(item: SkinItemProgress, mode: SkinMode): string {
  if (item.status === 'queued') return 'Queued';
  if (item.status === 'running') {
    const meta = modeMeta(mode);
    return `Enhancing · ${meta.engine} · ${meta.budget}/image`;
  }
  if (item.status === 'completed') {
    const faces = item.faces ?? 0;
    return `Enhanced ${faces} ${faces === 1 ? 'face' : 'faces'}`;
  }
  return '';
}
