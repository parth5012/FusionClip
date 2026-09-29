'use client';

// PROTOTYPE #125 — Variant A: "Inline segmented control"
// The mode toggle sits at the top of the existing upscaler sidebar and swaps
// the whole control cluster underneath it. Closest to today's VariantA form.

import React, { useMemo, useState } from 'react';
import {
  CreativeState,
  CREATIVE_DEFAULT,
  DEFAULT_PRECISION_STATE,
  ENGINES,
  PrecisionState,
  PrecisionPreset,
  PRECISION_PRESETS,
  SCALE_FACTORS,
  SOURCE_HEIGHT,
  SOURCE_WIDTH,
  SCALE_INT,
  buildPayload,
  resolvePreset,
} from './types';

function clampPct(v: number): number {
  return Math.max(0, Math.min(100, Math.round(v)));
}

export default function VariantA() {
  const [state, setState] = useState<PrecisionState>(DEFAULT_PRECISION_STATE);
  const [creative, setCreative] = useState<CreativeState>(CREATIVE_DEFAULT);

  const set = <K extends keyof PrecisionState>(k: K, v: PrecisionState[K]) =>
    setState((prev) => ({ ...prev, [k]: v }));

  const setSharpness = (v: number) => {
    const s = clampPct(v);
    setState((prev) => ({ ...prev, sharpness: s, preset: resolvePreset(s, prev.grain) }));
  };
  const setGrain = (v: number) => {
    const g = clampPct(v);
    setState((prev) => ({ ...prev, grain: g, preset: resolvePreset(prev.sharpness, g) }));
  };

  const applyPreset = (id: PrecisionPreset) => {
    const p = PRECISION_PRESETS.find((x) => x.id === id);
    if (!p) return;
    setState((prev) => ({ ...prev, preset: id, sharpness: p.sharpness, grain: p.grain }));
  };

  const payload = useMemo(() => buildPayload(state, creative), [state, creative]);
  const outW = SOURCE_WIDTH * SCALE_INT[state.scale];
  const outH = SOURCE_HEIGHT * SCALE_INT[state.scale];

  return (
    <div className="flex gap-4">
      {/* ---------------- sidebar ---------------- */}
      <aside className="w-[360px] shrink-0 bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-4">
        {/* mode toggle */}
        <div
          role="tablist"
          aria-label="Upscale mode"
          className="grid grid-cols-2 gap-1 bg-slate-950 border border-slate-800 rounded-lg p-1"
        >
          {(['creative', 'precision'] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={state.mode === m}
              onClick={() => set('mode', m)}
              className={`py-2 rounded-md text-xs font-semibold uppercase tracking-wide transition ${
                state.mode === m
                  ? m === 'precision'
                    ? 'bg-teal-500 text-slate-950'
                    : 'bg-sky-500 text-slate-950'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {state.mode === 'precision' ? (
          <>
            {/* engine */}
            <section>
              <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-2">
                Engine
              </h3>
              <div className="space-y-2">
                {ENGINES.map((e) => (
                  <button
                    key={e.id}
                    onClick={() => set('engine', e.id)}
                    aria-pressed={state.engine === e.id}
                    className={`w-full text-left rounded-lg border px-3 py-2.5 transition ${
                      state.engine === e.id
                        ? 'border-teal-500 bg-teal-500/10'
                        : 'border-slate-800 bg-slate-950 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-semibold text-slate-100">{e.name}</span>
                      {state.engine === e.id && (
                        <span className="text-[10px] font-bold text-teal-400">SELECTED</span>
                      )}
                    </div>
                    <div className="text-[11px] text-slate-400">{e.hint}</div>
                  </button>
                ))}
              </div>
            </section>

            {/* presets */}
            <section>
              <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-2">
                Preset
              </h3>
              <div className="flex gap-2">
                {PRECISION_PRESETS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => applyPreset(p.id)}
                    className={`flex-1 py-1.5 rounded-md text-xs font-semibold border transition ${
                      state.preset === p.id
                        ? 'border-teal-500 bg-teal-500/15 text-teal-300'
                        : 'border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {p.name}
                  </button>
                ))}
                <span
                  className={`flex-1 py-1.5 rounded-md text-xs font-semibold border text-center ${
                    state.preset === 'custom'
                      ? 'border-teal-500 bg-teal-500/15 text-teal-300'
                      : 'border-slate-800 text-slate-500'
                  }`}
                >
                  Custom
                </span>
              </div>
            </section>

            {/* sliders */}
            <section className="space-y-4">
              <div>
                <div className="flex items-baseline justify-between mb-1">
                  <label htmlFor="a-sharp" className="text-xs font-semibold text-slate-200">
                    Sharpness
                  </label>
                  <span className="font-mono text-xs text-teal-300">{state.sharpness}</span>
                </div>
                <input
                  id="a-sharp"
                  type="range"
                  min={0}
                  max={100}
                  value={state.sharpness}
                  onChange={(e) => setSharpness(Number(e.target.value))}
                  className="w-full accent-teal-500"
                  data-testid="precision-sharpness"
                />
                <div className="flex justify-between text-[10px] text-slate-600">
                  <span>0 faithful</span>
                  <span>100 crisp</span>
                </div>
              </div>

              <div>
                <div className="flex items-baseline justify-between mb-1">
                  <label htmlFor="a-grain" className="text-xs font-semibold text-slate-200">
                    Grain
                  </label>
                  <span className="font-mono text-xs text-teal-300">{state.grain}</span>
                </div>
                <input
                  id="a-grain"
                  type="range"
                  min={0}
                  max={100}
                  value={state.grain}
                  onChange={(e) => setGrain(Number(e.target.value))}
                  className="w-full accent-teal-500"
                  data-testid="precision-grain"
                />
                <div className="flex justify-between text-[10px] text-slate-600">
                  <span>0 clean</span>
                  <span>100 heavy</span>
                </div>
              </div>
            </section>
          </>
        ) : (
          <section className="space-y-3 opacity-70">
            <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">
              Creative controls (hidden in Precision)
            </h3>
            {(
              [
                ['Creativity', 'creativity'],
                ['Resemblance', 'resemblance'],
                ['Fractality', 'fractality'],
                ['HDR', 'hdr'],
              ] as const
            ).map(([label, key]) => (
              <div key={key}>
                <div className="flex items-baseline justify-between mb-1">
                  <span className="text-xs font-semibold text-slate-200">{label}</span>
                  <span className="font-mono text-xs text-sky-300">{creative[key]}</span>
                </div>
                <input
                  type="range"
                  min={-10}
                  max={10}
                  value={creative[key]}
                  onChange={(e) =>
                    setCreative((p) => ({ ...p, [key]: Number(e.target.value) }))
                  }
                  className="w-full accent-sky-500"
                />
              </div>
            ))}
            <div className="text-[11px] text-slate-500 border-t border-slate-800 pt-2">
              Category <b className="text-slate-300">{creative.category}</b> · prompt{' '}
              <span className="text-slate-400">&ldquo;{creative.prompt}&rdquo;</span>
            </div>
          </section>
        )}

        {/* scale — shared by both modes */}
        <section>
          <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-2">
            Scale
          </h3>
          <div className="grid grid-cols-4 gap-1">
            {SCALE_FACTORS.map((s) => (
              <button
                key={s}
                onClick={() => set('scale', s)}
                aria-pressed={state.scale === s}
                className={`py-2 rounded-md text-xs font-bold transition ${
                  state.scale === s
                    ? 'bg-slate-100 text-slate-950'
                    : 'bg-slate-950 border border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
                data-testid={`precision-scale-${s}`}
              >
                {s}
              </button>
            ))}
          </div>
        </section>

        <button
          className="w-full py-2.5 rounded-lg text-sm font-bold bg-teal-500 hover:bg-teal-400 text-slate-950 transition"
          data-testid="precision-run"
        >
          {state.mode === 'precision' ? 'Run Precision upscale' : 'Run Creative upscale'}
        </button>

        {/* state readout */}
        <section>
          <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-1">
            POST /api/upscale
          </h3>
          <pre
            data-testid="precision-payload"
            className="text-[10px] leading-relaxed font-mono text-emerald-300 bg-slate-950 border border-slate-800 rounded-lg p-2 overflow-x-auto"
          >
            {JSON.stringify(payload, null, 2)}
          </pre>
        </section>
      </aside>

      {/* ---------------- canvas ---------------- */}
      <div className="flex-1 bg-slate-950 border border-slate-800 rounded-xl overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-800 text-xs text-slate-400">
          <span>
            source {SOURCE_WIDTH}×{SOURCE_HEIGHT}
          </span>
          <span className="text-teal-300 font-mono">
            output {outW}×{outH}
          </span>
        </div>
        <div className="flex-1 relative bg-[radial-gradient(circle_at_30%_30%,#1e293b,#020617_70%)]">
          <div className="absolute inset-6 rounded-lg border border-dashed border-slate-800 flex items-center justify-center">
            <div className="text-center">
              <div className="text-4xl font-black text-slate-700">
                {state.mode === 'precision' ? 'PRECISION' : 'CREATIVE'}
              </div>
              <div className="text-xs text-slate-500 mt-1 font-mono">
                {state.mode === 'precision'
                  ? `${state.engine.toUpperCase()} · sharp ${state.sharpness} · grain ${state.grain} · ${state.scale}`
                  : `creativity ${creative.creativity} · hdr ${creative.hdr} · ${state.scale}`}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
