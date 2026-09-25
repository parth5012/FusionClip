export type ScaleFactor = '2x' | '4x' | '8x' | '16x';

export type PresetType = 'subtle' | 'vivid' | 'wild' | 'custom';

export type ContentCategory =
  | 'universal'
  | 'portraits'
  | 'landscapes'
  | 'anime'
  | 'architecture'
  | 'product';

export interface SliderValues {
  creativity: number; // -10 .. +10
  resemblance: number; // -10 .. +10
  fractality: number; // -10 .. +10
  hdr: number; // -10 .. +10
}

export interface PresetRecipe {
  name: string;
  description: string;
  sliders: SliderValues;
}

export const PRESET_RECIPES: Record<PresetType, PresetRecipe> = {
  subtle: {
    name: 'Subtle',
    description: 'Faithful structure preservation, minimal alteration, clean edge enhancement',
    sliders: { creativity: -4, resemblance: 7, fractality: -2, hdr: 1 },
  },
  vivid: {
    name: 'Vivid',
    description: 'Balanced hallucination with rich micro-textures and dynamic range',
    sliders: { creativity: 2, resemblance: 4, fractality: 2, hdr: 3 },
  },
  wild: {
    name: 'Wild',
    description: 'High generative freedom, deep hallucinated textures and surreal micro-detail',
    sliders: { creativity: 7, resemblance: -2, fractality: 6, hdr: 4 },
  },
  custom: {
    name: 'Custom',
    description: 'Freely configured diffusion and tile parameters',
    sliders: { creativity: 0, resemblance: 0, fractality: 0, hdr: 0 },
  },
};

export const CATEGORIES: { id: ContentCategory; label: string; description: string; icon: string }[] = [
  {
    id: 'universal',
    label: 'Universal',
    description: 'General purpose enhancement for mixed photos and graphics',
    icon: 'Sparkles',
  },
  {
    id: 'portraits',
    label: 'Portraits & People',
    description: 'Skin pores, realistic eyes, natural hair without plastic smoothing',
    icon: 'User',
  },
  {
    id: 'landscapes',
    label: 'Landscapes & Nature',
    description: 'Foliage, vegetation, rock textures, and atmospheric depth',
    icon: 'Mountain',
  },
  {
    id: 'anime',
    label: 'Anime & Digital Art',
    description: 'Sharp clean linework, flat shading preservation, vibrant tones',
    icon: 'Palette',
  },
  {
    id: 'architecture',
    label: 'Architecture & Interiors',
    description: 'Crisp planar lines, brick/mortar textures, and glass reflections',
    icon: 'Building2',
  },
  {
    id: 'product',
    label: 'Product & Studio',
    description: 'Clean packshots, controlled specular highlights, studio materials',
    icon: 'Package',
  },
];

export interface QueueItem {
  id: string;
  name: string;
  size: string;
  dimensions: string;
  targetScale: ScaleFactor;
  preset: PresetType;
  category: ContentCategory;
  prompt: string;
  status: 'idle' | 'queued' | 'tiling' | 'diffusing' | 'stitching' | 'completed' | 'error';
  progress: number;
  stepMessage?: string;
  previewUrl: string;
  resultUrl?: string;
  /** Backend task id once dispatched (absent while still pending in the bulk queue). */
  taskId?: string;
  /** Storage object key of the source image. */
  sourcePath?: string;
}

/**
 * Maps -10..+10 creativity slider to diffusion denoise strength [0.10, 0.65].
 * Piecewise so the default (0) lands exactly on 0.35 — must stay in lockstep
 * with backend `map_creativity_to_denoise` (#93/#96).
 */
export function mapCreativityToDenoise(val: number): number {
  const v = Math.max(-10, Math.min(10, val));
  return v <= 0
    ? Number((0.35 + (v / 10) * 0.25).toFixed(2))
    : Number((0.35 + (v / 10) * 0.3).toFixed(2));
}

/**
 * Maps -10..+10 resemblance slider to ControlNet conditioning weight [0.40, 1.20].
 * Piecewise so the default (0) lands exactly on 0.85 — mirrors backend
 * `map_resemblance_to_controlnet` (#93/#96).
 */
export function mapResemblanceToControlNet(val: number): number {
  const v = Math.max(-10, Math.min(10, val));
  return v <= 0
    ? Number((0.85 + (v / 10) * 0.45).toFixed(2))
    : Number((0.85 + (v / 10) * 0.35).toFixed(2));
}
