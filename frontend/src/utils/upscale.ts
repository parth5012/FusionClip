import {
  PRESET_RECIPES,
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
  type PresetType,
  type ScaleFactor,
} from '../components/upscale/types';

export { mapCreativityToDenoise, mapResemblanceToControlNet };

/** Maximum number of images a single bulk upscale run may enqueue (#96). */
export const MAX_BULK_QUEUE = 8;

const IMAGE_EXTENSIONS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'];

/** True when a storage object name is an image the upscaler can process. */
export function isUpscalableImage(name: string): boolean {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return IMAGE_EXTENSIONS.includes(ext);
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
