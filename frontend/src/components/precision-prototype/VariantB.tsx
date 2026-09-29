'use client';

// PROTOTYPE #125 — Variant B: "Canvas HUD"
// No sidebar at all. Mode is a chip in the viewport header, scale/engine live
// in a top-right stepper, and Sharpness/Grain sit in a collapsible bottom
// drawer over the image. The picture is the interface.

import React, { useMemo, useState } from 'react';
import {
  CreativeState,
  CREATIVE_DEFAULT,
  DEFAULT_PRECISION_STATE,
  ENGINES,
  PrecisionState,
  PRECISION_PRESETS,
  SCALE_FACTORS,
  SCALE_INT,
  SOURCE_HEIGHT,
  SOURCE_WIDTH,
  buildPayload,
  resolvePreset,
} from './types';

const clampPct = (v: number) => Math.max(0, Math.min(100, Math.round(v)));

export default function VariantB() {
  const [state, setState] = useState<PrecisionState>(DEFAULT_PRECISION_STATE);
  const [creative, setCreative] = useState<CreativeState>(CREATIVE_DEFAULT);
  const [drawerOpen, setDrawerOpen] = useState(true);

  const set = <K extends keyof PrecisionState>(k: K, v: PrecisionState[K]) =>
    setState((prev) => ({ ...prev, [k]: v }));

  const payload = useMemo(() => buildPayload(state, creative), [state, creative]);
  const outW = SOURCE_WIDTH * SCALE_INT[state.scale];
  const outH = SOURCE_HEIGHT * SCALE_INT[state.scale];
  const activePreset = PRECISION_PRESETS.find(
    (p) => p.sharpness === state.sharpness && p.grain === state.grain
  );

  return (
    <div className="relative h-[70vh] min-h-[520px] rounded-xl overflow-hidden border border-slate-800 bg-[radial-gradient(circle_at_60%_40%,#134e4a,#020617_65%)]">
      {/* ---- top bar ---- */}
      <div className="absolute inset-x-0 top-0 flex items-start justify-between gap-3 p-3">
        {/* mode chip */}
        <div className="flex items-center gap-1 rounded-full bg-slate-950/85 border border-slate-800 p-1 backdrop-blur">
          {(['creative', 'precision'] as const).map((m) => (
            <button
              key={m}
              onClick={() => set('mode', m)}
              aria-pressed={state.mode === m}
              className={`px-3 py-1.5 rounded-full text-[11px] font-bold uppercase tracking-wide transition ${
                state.mode === m
                  ? m === 'precision'
                    ? 'bg-teal-400 text-slate-950'
                    : 'bg-sky-400 text-slate-950'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {/* scale stepper + engine pill */}
        <div className="flex items-center gap-2">
          <div className="flex items-center rounded-full bg-slate-950/85 border border-slate-800 p-1 backdrop-blur">
            {SCALE_FACTORS.map((s) => (
              <button
                key={s}
                onClick={() => set('scale', s)}
                aria-pressed={state.scale === s}
                className={`px-2.5 py-1.5 rounded-full text-[11px] font-bold transition ${
                  state.scale === s
                    ? 'bg-slate-100 text-slate-950'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
                data-testid={`precision-scale-${s}`}
              >
                {s}
              </button>
            ))}
          </div>
          <button
            onClick={() =>
              set('engine', state.engine === 'hat' ? 'scunet' : 'hat')
            }
            className="px-3 py-2 rounded-full bg-slate-950/85 border border-teal-500/50 text-[11px] font-bold text-teal-300 backdrop-blur hover:bg-teal-500/15 transition"
            title="Cycle SR engine"
          >
            {state.engine.toUpperCase()} ↻
          </button>
        </div>
      </div>

      {/* ---- centre readout ---- */}
      <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
        <div className="text-center">
          <div className="text-6xl font-black text-white/10 tracking-tight">
            {outW}×{outH}
          </div>
          <div className="text-xs text-slate-400 font-mono mt-2">
            {state.mode === 'precision'
              ? `precision · ${state.engine} · ${state.scale} · sharp ${state.sharpness} · grain ${state.grain}`
              : `creative · ${creative.category} · ${state.scale}`}
          </div>
        </div>
      </div>

      {/* ---- bottom drawer ---- */}
      <div className="absolute inset-x-0 bottom-0 bg-slate-950/92 border-t border-slate-800 backdrop-blur">
        <button
          onClick={() => setDrawerOpen((o) => !o)}
          className="w-full flex items-center justify-between px-4 py-2 text-[11px] font-bold uppercase tracking-wider text-slate-400 hover:text-slate-200"
        >
          <span>{state.mode} controls</span>
          <span>{drawerOpen ? '▾ hide' : '▴ show'}</span>
        </button>

        {drawerOpen && (
          <div className="px-4 pb-4 space-y-3">
            {state.mode === 'precision' ? (
              <>
                <div className="flex flex-wrap gap-2">
                  {PRECISION_PRESETS.map((p) => (
                    <button
                      key={p.id}
                      onClick={() =>
                        setState((prev) => ({
                          ...prev,
                          preset: p.id,
                          sharpness: p.sharpness,
                          grain: p.grain,
                        }))
                      }
                      className={`px-3 py-1.5 rounded-full text-[11px] font-semibold border transition ${
                        activePreset?.id === p.id
                          ? 'border-teal-400 bg-teal-400/15 text-teal-300'
                          : 'border-slate-800 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {p.name}
                      <span className="ml-1.5 opacity-60">
                        {p.sharpness}/{p.grain}
                      </span>
                    </button>
                  ))}
                  <span className="px-3 py-1.5 rounded-full text-[11px] font-semibold border border-slate-800 text-slate-500">
                    {activePreset ? 'preset' : 'custom'}
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <div className="flex items-baseline justify-between mb-1">
                      <label htmlFor="b-sharp" className="text-[11px] font-semibold text-slate-300">
                        Sharpness
                      </label>
                      <span className="font-mono text-xs text-teal-300">{state.sharpness}</span>
                    </div>
                    <input
                      id="b-sharp"
                      type="range"
                      min={0}
                      max={100}
                      value={state.sharpness}
                      onChange={(e) => {
                        const s = clampPct(Number(e.target.value));
                        setState((p) => ({
                          ...p,
                          sharpness: s,
                          preset: resolvePreset(s, p.grain),
                        }));
                      }}
                      className="w-full accent-teal-400"
                      data-testid="precision-sharpness"
                    />
                  </div>
                  <div>
                    <div className="flex items-baseline justify-between mb-1">
                      <label htmlFor="b-grain" className="text-[11px] font-semibold text-slate-300">
                        Grain
                      </label>
                      <span className="font-mono text-xs text-teal-300">{state.grain}</span>
                    </div>
                    <input
                      id="b-grain"
                      type="range"
                      min={0}
                      max={100}
                      value={state.grain}
                      onChange={(e) => {
                        const g = clampPct(Number(e.target.value));
                        setState((p) => ({
                          ...p,
                          grain: g,
                          preset: resolvePreset(p.sharpness, g),
                        }));
                      }}
                      className="w-full accent-teal-400"
                      data-testid="precision-grain"
                    />
                  </div>
                </div>

                <div className="text-[11px] text-slate-500">
                  {ENGINES.find((e) => e.id === state.engine)?.role} —{' '}
                  {ENGINES.find((e) => e.id === state.engine)?.hint}
                </div>
              </>
            ) : (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 opacity-75">
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
                      <span className="text-[11px] font-semibold text-slate-300">{label}</span>
                      <span className="font-mono text-[11px] text-sky-300">{creative[key]}</span>
                    </div>
                    <input
                      type="range"
                      min={-10}
                      max={10}
                      value={creative[key]}
                      onChange={(e) =>
                        setCreative((p) => ({ ...p, [key]: Number(e.target.value) }))
                      }
                      className="w-full accent-sky-400"
                    />
                  </div>
                ))}
              </div>
            )}

            <pre
              data-testid="precision-payload"
              className="text-[10px] leading-relaxed font-mono text-emerald-300 bg-slate-900/70 border border-slate-800 rounded-md p-2 overflow-x-auto"
            >
              {JSON.stringify(payload, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
