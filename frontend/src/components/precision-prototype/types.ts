// PROTOTYPE #125 — throwaway. Shared state for the three Precision-mode variants.
// Decisions locked in #123 drive every shape here (engine set, slider ranges,
// API field names, preset recipes).

export type PrecisionMode = 'creative' | 'precision';

export type PrecisionEngine = 'hat' | 'scunet';

export type PrecisionScale = '2x' | '4x' | '8x' | '16x';

export type PrecisionPreset = 'clean' | 'filmic' | 'custom';

export interface PrecisionState {
  mode: PrecisionMode;
  engine: PrecisionEngine;
  /** 0..100 — Magnific Sharpness parity. */
  sharpness: number;
  /** 0..100 — Magnific Grain parity. */
  grain: number;
  scale: PrecisionScale;
  preset: PrecisionPreset;
}

export const SCALE_FACTORS: PrecisionScale[] = ['2x', '4x', '8x', '16x'];

export const SCALE_INT: Record<PrecisionScale, number> = {
  '2x': 2,
  '4x': 4,
  '8x': 8,
  '16x': 16,
};

/** Placeholder source dimensions so the rung cards can show real output sizes. */
export const SOURCE_WIDTH = 1024;
export const SOURCE_HEIGHT = 768;

export interface EngineSpec {
  id: PrecisionEngine;
  name: string;
  hint: string;
  vram: string;
  latency: string;
  role: string;
}

export const ENGINES: EngineSpec[] = [
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

export interface PrecisionPresetSpec {
  id: PrecisionPreset;
  name: string;
  sharpness: number;
  grain: number;
}

export const PRECISION_PRESETS: PrecisionPresetSpec[] = [
  { id: 'clean', name: 'Clean', sharpness: 15, grain: 0 },
  { id: 'filmic', name: 'Filmic', sharpness: 40, grain: 25 },
];

/** Creative-mode controls, kept only so the variants can show what Precision hides. */
export interface CreativeState {
  creativity: number;
  resemblance: number;
  fractality: number;
  hdr: number;
  category: string;
  prompt: string;
}

export const CREATIVE_DEFAULT: CreativeState = {
  creativity: 0,
  resemblance: 0,
  fractality: 0,
  hdr: 0,
  category: 'portraits',
  prompt: 'high fidelity, skin pores, natural lighting, 8k uhd',
};

export const DEFAULT_PRECISION_STATE: PrecisionState = {
  mode: 'precision',
  engine: 'hat',
  sharpness: 15,
  grain: 0,
  scale: '4x',
  preset: 'clean',
};

export function resolvePreset(
  sharpness: number,
  grain: number
): PrecisionPreset {
  const hit = PRECISION_PRESETS.find(
    (p) => p.sharpness === sharpness && p.grain === grain
  );
  return hit ? hit.id : 'custom';
}

/**
 * The exact body #124 will accept (decision 11 in #123).
 * Creative-only fields are omitted in precision mode, and precision-only
 * fields are omitted in creative mode — the backend rejects them otherwise.
 */
export function buildPayload(state: PrecisionState, creative: CreativeState) {
  if (state.mode === 'precision') {
    return {
      mode: 'precision',
      scale: SCALE_INT[state.scale],
      engine: state.engine,
      sharpness: state.sharpness,
      grain: state.grain,
    };
  }
  return {
    mode: 'creative',
    scale: SCALE_INT[state.scale],
    category: creative.category,
    creativity: creative.creativity,
    resemblance: creative.resemblance,
    fractality: creative.fractality,
    hdr: creative.hdr,
    prompt: creative.prompt,
  };
}
