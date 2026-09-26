/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * Data model transcribed from the #111 grilling resolution so every variant
 * argues about layout with the *same* constraints rather than inventing its own.
 */

// Same photo at two renderings stands in for "before" (soft, low-res) and
// "after" (detailed), the same trick the upscale prototype used.
export const PORTRAIT = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=40';
export const PORTRAIT_AFTER = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=1600&q=95';
export const PORTRAIT_B = 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=600&q=40';
export const PORTRAIT_B_AFTER = 'https://images.unsplash.com/photo-1506794778202-cad84cf45f1d?auto=format&fit=crop&w=1600&q=95';

export type SkinMode = 'faithful' | 'creative' | 'flexible';

export const MODES: { id: SkinMode; label: string; engine: string; budget: string; blurb: string }[] = [
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

/** Verbatim Magnific `optimized_for` values — #111 decision 3, no renaming. */
export const FLEXIBLE_PRESETS: { id: string; label: string; blurb: string }[] = [
  { id: 'enhance_skin', label: 'enhance_skin', blurb: 'The default. Clean up and even out tone.' },
  { id: 'improve_lighting', label: 'improve_lighting', blurb: 'Lift flat or uneven lighting on the face.' },
  { id: 'enhance_everything', label: 'enhance_everything', blurb: 'Whole-image lift, not just skin.' },
  { id: 'transform_to_real', label: 'transform_to_real', blurb: 'Push a stylised render toward photoreal.' },
  { id: 'no_make_up', label: 'no_make_up', blurb: 'Reduce visible cosmetics rather than enhance them.' },
];

/**
 * #111 decision 2: `skin_detail` is NOT the same physical knob per mode.
 * DiffBIR exposes a guidance scale; GFPGAN exposes nothing, so Faithful
 * substitutes a post-filter. Any variant that shows this slider must show
 * which meaning is live, or the label lies.
 */
export function skinDetailMeaning(mode: SkinMode): { engine: string; meaning: string } {
  return mode === 'faithful'
    ? { engine: 'post-filter', meaning: 'texture retention after restore' }
    : { engine: 'DiffBIR guidance', meaning: 'fidelity vs. stylisation' };
}

export interface SkinState {
  mode: SkinMode;
  preset: string;
  sharpen: number;
  smartGrain: number;
  skinDetail: number;
}

export const INITIAL_SKIN: SkinState = {
  mode: 'faithful',
  preset: 'enhance_skin',
  sharpen: 40,
  smartGrain: 20,
  skinDetail: 80, // Magnific's documented default
};

export function clamp(v: number): number {
  return Math.max(0, Math.min(100, v));
}
