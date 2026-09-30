import {
  PRESET_RECIPES,
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
  type PresetType,
  type ScaleFactor,
  type PrecisionMode,
  type PrecisionEngine,
  type PrecisionPreset,
  type PrecisionSliderValues,
  type PrecisionEngineSpec,
  type PrecisionPresetSpec,
} from '../components/upscale/types';
import type { UpscalePayload } from './api';

export { mapCreativityToDenoise, mapResemblanceToControlNet };
export type {
  PrecisionMode,
  PrecisionEngine,
  PrecisionPreset,
  PrecisionSliderValues,
  PrecisionEngineSpec,
  PrecisionPresetSpec,
};

/** Default source dimensions for computing scale rung preview sizes (#142). */
export const DEFAULT_SOURCE_WIDTH = 1024;
export const DEFAULT_SOURCE_HEIGHT = 768;

/** Precision engine registry (#123-d10, #142). */
export const PRECISION_ENGINES: PrecisionEngineSpec[] = [
  {
    id: 'hat',
    name: 'HAT',
    hint: 'Clean sources — highest detail recovery',
    vram: '≈2.3 GiB tiled @16x',
    latency: 'medium',
    role: 'faithful SR on every stage of the chain',
  },
  {
    id: 'scunet',
    name: 'SCUNet',
    hint: 'Noisy / ISO-heavy sources',
    vram: '≈2.1 GiB tiled @16x',
    latency: 'medium',
    role: 'denoise into stage 1, then HAT finishes the chain',
  },
];

/** Precision mode preset definitions (#142). */
export const PRECISION_PRESETS: Record<'clean' | 'filmic', PrecisionPresetSpec> = {
  clean: { id: 'clean', name: 'Clean', sharpness: 15, grain: 0 },
  filmic: { id: 'filmic', name: 'Filmic', sharpness: 40, grain: 25 },
};

/**
 * Determine the matching preset ('clean' | 'filmic' | 'custom') from current
 * sharpness and grain levels (#142).
 */
export function resolvePrecisionPreset(
  sharpness: number,
  grain: number,
): PrecisionPreset {
  if (
    sharpness === PRECISION_PRESETS.clean.sharpness &&
    grain === PRECISION_PRESETS.clean.grain
  ) {
    return 'clean';
  }
  if (
    sharpness === PRECISION_PRESETS.filmic.sharpness &&
    grain === PRECISION_PRESETS.filmic.grain
  ) {
    return 'filmic';
  }
  return 'custom';
}

/** Clamp precision slider percentage input to an integer in [0, 100]. */
export function clampPrecisionPct(val: number): number {
  if (!Number.isFinite(val)) return 0;
  return Math.max(0, Math.min(100, Math.round(val)));
}

/** Calculate the number of 2x chain stages for a given scale factor. */
export function getPrecisionStages(scale: ScaleFactor | number): number {
  const scaleInt = typeof scale === 'number' ? scale : scaleFactorToInt(scale);
  return Math.max(1, Math.round(Math.log2(scaleInt)));
}

/** Format progressive chain stage caption, e.g. "2 × 2x stages" (#142). */
export function formatRungStages(scale: ScaleFactor | number): string {
  const stages = getPrecisionStages(scale);
  return `${stages} × 2x ${stages === 1 ? 'stage' : 'stages'}`;
}

/** Compute numeric output dimensions for a given scale factor and source dimensions. */
export function computeRungDimensions(
  scale: ScaleFactor | number,
  sourceW: number = DEFAULT_SOURCE_WIDTH,
  sourceH: number = DEFAULT_SOURCE_HEIGHT,
): { width: number; height: number } {
  const scaleInt = typeof scale === 'number' ? scale : scaleFactorToInt(scale);
  return {
    width: sourceW * scaleInt,
    height: sourceH * scaleInt,
  };
}

/** Format output pixel dimensions string, e.g. "4096×3072" (#142). */
export function formatRungOutputPx(
  scale: ScaleFactor | number,
  sourceW: number = DEFAULT_SOURCE_WIDTH,
  sourceH: number = DEFAULT_SOURCE_HEIGHT,
): string {
  const dims = computeRungDimensions(scale, sourceW, sourceH);
  return `${dims.width}×${dims.height}`;
}

/** Maximum number of images a single bulk upscale run may enqueue (#96). */
export const MAX_BULK_QUEUE = 8;

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'];

/** True when a storage object name is an image file (both heavy jobs are images-only). */
export function isImageFile(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return IMAGE_EXTENSIONS.includes(ext);
}

/** True when a storage object name is an image the upscaler can process. */
export function isUpscalableImage(name: string): boolean {
  return isImageFile(name);
}

/** '4x' -> 4 for the POST /api/upscale payload. */
export function scaleFactorToInt(scale: ScaleFactor | string): number {
  const parsed = Number.parseInt(String(scale).replace(/x$/i, ''), 10);
  return Number.isFinite(parsed) ? parsed : 4;
}

export interface UpscaleParams {
  preset: PresetType;
  scale: number;
  creativity: number;
  resemblance: number;
  fractality: number;
  hdr: number;
  category: string;
  prompt?: string;
}

export interface UpscaleParamOverrides {
  scale?: ScaleFactor | number;
  creativity?: number;
  resemblance?: number;
  fractality?: number;
  hdr?: number;
  category?: string;
  prompt?: string;
}

/**
 * Merge preset slider defaults with explicit overrides into the exact
 * payload shape POST /api/upscale expects.
 */
export function resolveUpscaleParams(
  preset: PresetType,
  overrides: UpscaleParamOverrides = {},
): UpscaleParams {
  const recipe = PRESET_RECIPES[preset] ?? PRESET_RECIPES.vivid;
  const scale =
    typeof overrides.scale === 'number'
      ? overrides.scale
      : scaleFactorToInt(overrides.scale ?? '4x');

  return {
    preset,
    scale,
    creativity: overrides.creativity ?? recipe.sliders.creativity,
    resemblance: overrides.resemblance ?? recipe.sliders.resemblance,
    fractality: overrides.fractality ?? recipe.sliders.fractality,
    hdr: overrides.hdr ?? recipe.sliders.hdr,
    category: overrides.category ?? 'universal',
    prompt: overrides.prompt,
  };
}

export interface BuildUpscalePayloadParams {
  image_path: string;
  scale: ScaleFactor | number;
  mode?: PrecisionMode;
  // Precision mode inputs (#142, #123-d11)
  engine?: PrecisionEngine;
  sharpness?: number;
  grain?: number;
  // Creative mode inputs
  preset?: PresetType;
  category?: string;
  creativity?: number;
  resemblance?: number;
  fractality?: number;
  hdr?: number;
  prompt?: string;
}

/**
 * Builds the exact JSON payload expected by POST /api/upscale (#142, #123-d11).
 *
 * Mode contract:
 * - In precision mode: engine, sharpness, grain are sent; creative-only fields
 *   (creativity, resemblance, fractality, hdr, preset, category, prompt) MUST be omitted.
 * - In creative mode: creativity, resemblance, fractality, hdr, category, prompt are sent;
 *   precision-only fields (engine, sharpness, grain) MUST be omitted.
 */
export function buildUpscalePayload(params: BuildUpscalePayloadParams): UpscalePayload {
  const scale = typeof params.scale === 'number' ? params.scale : scaleFactorToInt(params.scale);
  const mode: PrecisionMode = params.mode === 'precision' ? 'precision' : 'creative';

  if (mode === 'precision') {
    return {
      image_path: params.image_path,
      scale,
      mode: 'precision',
      engine: params.engine ?? 'hat',
      sharpness: clampPrecisionPct(params.sharpness ?? 0),
      grain: clampPrecisionPct(params.grain ?? 0),
    };
  }

  const recipe = PRESET_RECIPES[params.preset ?? 'vivid'] ?? PRESET_RECIPES.vivid;
  const clampSlider = (v: number) => Math.max(-10, Math.min(10, Math.round(v)));

  const payload: UpscalePayload = {
    image_path: params.image_path,
    scale,
    mode: 'creative',
    preset: params.preset ?? 'vivid',
    creativity: clampSlider(params.creativity ?? recipe.sliders.creativity),
    resemblance: clampSlider(params.resemblance ?? recipe.sliders.resemblance),
    fractality: clampSlider(params.fractality ?? recipe.sliders.fractality),
    hdr: clampSlider(params.hdr ?? recipe.sliders.hdr),
    category: params.category ?? 'universal',
  };

  if (params.prompt && params.prompt.trim()) {
    payload.prompt = params.prompt.trim();
  }

  return payload;
}
