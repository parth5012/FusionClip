/**
 * Image Editor recipe contract (#121, map #75).
 *
 * The versioned edit-recipe JSON is the source of truth (#118): the client
 * preview is CSS-only (`recipeToFilter`), the backend POST /api/editor/render
 * is the authoritative re-render, and `recipeToFfmpegFilter` is the mapping a
 * future Celery/ffmpeg worker would consume (kept next to the CSS factors so
 * the two cannot drift). Ranges mirror `backend/app/ml/image_adjust.py`
 * exactly; validation here refuses before the request is sent, the backend
 * answers 400 for the same value, and neither side ever clamps.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** Recipe schema version — bumped only on a breaking recipe-shape change. */
export const RECIPE_VERSION = 1;

export type CropAspect = 'free' | '1:1' | '4:3' | '16:9';

export interface EditorRecipe {
  exposure: number; // -100..100
  brightness: number;
  contrast: number;
  highlights: number;
  shadows: number;
  tint: number; // -100..100 (green-magenta)
  grain: number; // 0..100
  rotate: number; // -45..45 deg
  cropAspect: CropAspect;
}

export const DEFAULT_RECIPE: EditorRecipe = {
  exposure: 0,
  brightness: 0,
  contrast: 0,
  highlights: 0,
  shadows: 0,
  tint: 0,
  grain: 0,
  rotate: 0,
  cropAspect: 'free',
};

export type AdjustOpKey = 'exposure' | 'brightness' | 'contrast' | 'highlights' | 'shadows' | 'tint' | 'grain';

export interface SliderMeta {
  key: AdjustOpKey;
  label: string;
  min: number;
  max: number;
}

/** The 7 Adjust ops (#119 v1 scope) with their slider ranges. */
export const SLIDERS: SliderMeta[] = [
  { key: 'exposure', label: 'Exposure', min: -100, max: 100 },
  { key: 'brightness', label: 'Brightness', min: -100, max: 100 },
  { key: 'contrast', label: 'Contrast', min: -100, max: 100 },
  { key: 'highlights', label: 'Highlights', min: -100, max: 100 },
  { key: 'shadows', label: 'Shadows', min: -100, max: 100 },
  { key: 'tint', label: 'Tint', min: -100, max: 100 },
  { key: 'grain', label: 'Grain', min: 0, max: 100 },
];

export const ROTATE_RANGE = { min: -45, max: 45, default: 0 } as const;

export const CROP_ASPECTS: readonly CropAspect[] = ['free', '1:1', '4:3', '16:9'];

const KNOWN_KEYS: readonly string[] = [
  ...SLIDERS.map((s) => s.key),
  'rotate',
  'cropAspect',
];

function sliderError(name: string, value: unknown, min: number, max: number): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return `Slider '${name}' value ${String(value)} must be a finite whole number: the wire format is an integer ${min}..${max} range.`;
  }
  if (!Number.isInteger(value)) {
    return `Slider '${name}' value ${value} must be a whole number: the wire format is an integer ${min}..${max} range.`;
  }
  if (value < min || value > max) {
    return `Slider '${name}' value ${value} is out of range: must be between ${min} and ${max}. Values are not clamped.`;
  }
  return null;
}

export type RecipeValidation =
  | { ok: true; recipe: EditorRecipe }
  | { ok: false; field: string; error: string };

/**
 * Validate a partial recipe and fill defaults.
 *
 * Unknown keys are refused (a typo'd op must not silently do nothing);
 * out-of-range / fractional values are refused, never clamped — the backend
 * answers 400 for the same value.
 */
export function validateRecipe(raw: unknown): RecipeValidation {
  const input = (raw ?? {}) as Record<string, unknown>;
  if (typeof input !== 'object' || Array.isArray(input)) {
    return { ok: false, field: 'recipe', error: 'Invalid recipe: must be a JSON object of op names to integers.' };
  }
  const unknown = Object.keys(input).filter((k) => !KNOWN_KEYS.includes(k)).sort();
  if (unknown.length > 0) {
    return { ok: false, field: unknown[0], error: `Unknown recipe key(s) ${unknown.join(', ')}. Unknown keys are refused, never ignored.` };
  }
  const recipe: EditorRecipe = { ...DEFAULT_RECIPE };
  for (const s of SLIDERS) {
    if (s.key in input) {
      const error = sliderError(s.key, input[s.key], s.min, s.max);
      if (error) return { ok: false, field: s.key, error };
      recipe[s.key] = input[s.key] as number;
    }
  }
  if ('rotate' in input) {
    const error = sliderError('rotate', input.rotate, ROTATE_RANGE.min, ROTATE_RANGE.max);
    if (error) return { ok: false, field: 'rotate', error };
    recipe.rotate = input.rotate as number;
  }
  if ('cropAspect' in input) {
    const aspect = input.cropAspect as string;
    if (!CROP_ASPECTS.includes(aspect as CropAspect)) {
      return { ok: false, field: 'cropAspect', error: `Invalid cropAspect '${aspect}': must be one of ${CROP_ASPECTS.join(', ')}.` };
    }
    recipe.cropAspect = aspect as CropAspect;
  }
  return { ok: true, recipe };
}

/**
 * CSS-only client preview (same mapping as the #120 prototype).
 * exposure+brightness share one brightness term, tint rides hue-rotate,
 * shadows ride saturation. The server is authoritative; this is a preview.
 */
export function recipeToFilter(r: EditorRecipe): string {
  const b = 1 + (r.exposure + r.brightness) / 200;
  const c = 1 + r.contrast / 150;
  const h = r.tint / 4; // deg approx
  return `brightness(${b.toFixed(3)}) contrast(${c.toFixed(3)}) hue-rotate(${h.toFixed(1)}deg) saturate(${(1 + r.shadows / 300).toFixed(3)})`;
}

/**
 * Forward-compatible ffmpeg mapping for a future Celery worker.
 * Mirrors `recipe_to_ffmpeg_filter` in backend/app/ml/image_adjust.py —
 * kept in lockstep, not executed by the v1 synchronous path.
 */
export function recipeToFfmpegFilter(r: EditorRecipe): string {
  const brightness = (r.exposure + r.brightness) / 200;
  const contrast = 1 + r.contrast / 150;
  const saturation = 1 + r.shadows / 300;
  const parts = [
    `eq=brightness=${brightness.toFixed(4)}:contrast=${contrast.toFixed(4)}:saturation=${saturation.toFixed(4)}`,
  ];
  if (r.tint) parts.push(`hue=h=${(r.tint / 4).toFixed(1)}`);
  if (r.grain) parts.push(`noise=alls=${Math.round((r.grain / 100) * 25)}:allf=t`);
  return parts.join(',');
}

/** Stable serialization: sorted keys, no whitespace variance. */
export function canonicalRecipe(r: EditorRecipe): string {
  const sorted: Record<string, unknown> = {};
  for (const key of Object.keys(r).sort()) {
    sorted[key] = (r as unknown as Record<string, unknown>)[key];
  }
  return JSON.stringify(sorted);
}

/** Deterministic FNV-1a fingerprint of the canonical recipe. */
export function recipeFingerprint(r: EditorRecipe): number {
  const text = canonicalRecipe(r);
  let hash = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash;
}

export function isDefaultRecipe(r: EditorRecipe): boolean {
  return canonicalRecipe(r) === canonicalRecipe(DEFAULT_RECIPE);
}

/* ── Editor HTTP client (POST /api/editor/*) ─────────────────────────── */

export interface EditorVersion {
  version: number;
  recipe_version?: number;
  file_path: string;
  url: string;
  recipe: EditorRecipe;
  created_at?: string | null;
}

export interface EditorSaveResponse {
  status: string;
  version: number;
  recipe_version: number;
  source_path: string;
  file_path: string;
  url: string;
  recipe: EditorRecipe;
}

export interface EditorRenderResponse {
  status: string;
  recipe_version: number;
  source_path: string;
  filename: string;
  url: string;
  recipe_path: string;
  recipe_url: string;
  version: number;
  image_size: [number, number];
  parameters: EditorRecipe;
}

async function readEditorError(res: Response, fallback: string): Promise<string> {
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = err?.detail;
  if (typeof detail === 'string') return detail;
  if (detail) return JSON.stringify(detail);
  return fallback;
}

/** Persist one versioned edit-recipe JSON sidecar (Apply leg). */
export async function saveEditorRecipe(
  sourcePath: string,
  recipe: EditorRecipe,
): Promise<EditorSaveResponse> {
  const res = await fetch(`${API_BASE_URL}/api/editor/recipe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: sourcePath, recipe }),
  });
  if (!res.ok) throw new Error(await readEditorError(res, 'Failed to save edit recipe'));
  return res.json();
}

/** All persisted recipe versions for a source, oldest first (reload leg). */
export async function fetchEditorRecipes(sourcePath: string): Promise<EditorVersion[]> {
  const res = await fetch(
    `${API_BASE_URL}/api/editor/recipes?source_path=${encodeURIComponent(sourcePath)}`,
  );
  if (!res.ok) throw new Error(await readEditorError(res, 'Failed to fetch edit recipes'));
  const body = await res.json();
  return body.versions ?? [];
}

/** Authoritative re-render + export (Export leg). Synchronous in v1. */
export async function renderEditorImage(
  sourcePath: string,
  recipe: EditorRecipe,
): Promise<EditorRenderResponse> {
  const res = await fetch(`${API_BASE_URL}/api/editor/render`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source_path: sourcePath, recipe }),
  });
  if (!res.ok) throw new Error(await readEditorError(res, 'Failed to render edit'));
  return res.json();
}
