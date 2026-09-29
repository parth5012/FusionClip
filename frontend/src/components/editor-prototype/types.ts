'use client';
// PROTOTYPE (#120) — throwaway, do not ship. Answers: editor shell layout for Adjust + crop/rotate.

export interface EditorRecipe {
  exposure: number; // -100..100
  brightness: number;
  contrast: number;
  highlights: number;
  shadows: number;
  tint: number; // -100..100 (green-magenta)
  grain: number; // 0..100
  rotate: number; // -45..45 deg (v1 includes rotate per #119)
  cropAspect: 'free' | '1:1' | '4:3' | '16:9';
  showBeforeAfter: boolean;
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
  showBeforeAfter: false,
};

// CSS preview only — Celery/ffmpeg is authoritative (#118). exposure->brightness, contrast->contrast, tint->hue-rotate approx.
export function recipeToFilter(r: EditorRecipe): string {
  const b = 1 + (r.exposure + r.brightness) / 200;
  const c = 1 + r.contrast / 150;
  const h = r.tint / 4; // deg approx
  return `brightness(${b.toFixed(3)}) contrast(${c.toFixed(3)}) hue-rotate(${h.toFixed(1)}deg) saturate(${(1 + r.shadows / 300).toFixed(3)})`;
}

export const SLIDERS: { key: keyof EditorRecipe; label: string; min: number; max: number }[] = [
  { key: 'exposure', label: 'Exposure', min: -100, max: 100 },
  { key: 'brightness', label: 'Brightness', min: -100, max: 100 },
  { key: 'contrast', label: 'Contrast', min: -100, max: 100 },
  { key: 'highlights', label: 'Highlights', min: -100, max: 100 },
  { key: 'shadows', label: 'Shadows', min: -100, max: 100 },
  { key: 'tint', label: 'Tint', min: -100, max: 100 },
  { key: 'grain', label: 'Grain', min: 0, max: 100 },
];
