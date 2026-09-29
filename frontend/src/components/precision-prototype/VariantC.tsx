'use client';

// PROTOTYPE #125 — Variant C: "Rung grid / spec sheet"
// Mode is a pair of selectable columns rather than a toggle; scale becomes four
// rung cards with computed output dimensions; the engine is a comparison table;
// Sharpness/Grain are numeric steppers instead of range inputs.

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
} from './types';

const clampPct = (v: number) => Math.max(0, Math.min(100, Math.round(v)));

function Stepper({
  label,
  value,
  onChange,
  testId,
  hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  testId: string;
  hint: string;
}) {
  return (
    <div className="border border-slate-800 rounded-lg p-3 bg-slate-950">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
          {label}
        </span>
        <span className="font-mono text-lg font-bold text-amber-300" data-testid={testId}>
          {value}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-slate-900 overflow-hidden mb-3">
        <div
          className="h-full bg-amber-400 transition-all"
          style={{ width: `${value}%` }}
        />
      </div>
      <div className="flex items-center gap-2">
        <button
          onClick={() => onChange(clampPct(value - 5))}
          className="w-7 h-7 rounded border border-slate-800 text-slate-300 hover:bg-slate-900"
          aria-label={`decrease ${label}`}
        >
          −
        </button>
        <input
          type="number"
          min={0}
          max={100}
          value={value}
          onChange={(e) => onChange(clampPct(Number(e.target.value)))}
          className="flex-1 w-full bg-slate-900 border border-slate-800 rounded px-2 py-1 text-xs font-mono text-slate-100"
          aria-label={label}
        />
        <button
          onClick={() => onChange(clampPct(value + 5))}
          className="w-7 h-7 rounded border border-slate-800 text-slate-300 hover:bg-slate-900"
          aria-label={`increase ${label}`}
        >
          +
        </button>
      </div>
      <div className="text-[10px] text-slate-600 mt-2">{hint}</div>
    </div>
  );
}

export default function VariantC() {
  const [state, setState] = useState<PrecisionState>(DEFAULT_PRECISION_STATE);
  const [creative, setCreative] = useState<CreativeState>(CREATIVE_DEFAULT);

  const set = <K extends keyof PrecisionState>(k: K, v: PrecisionState[K]) =>
    setState((prev) => ({ ...prev, [k]: v }));

  const payload = useMemo(() => buildPayload(state, creative), [state, creative]);
  const activePreset = PRECISION_PRESETS.find(
    (p) => p.sharpness === state.sharpness && p.grain === state.grain
  );

  return (
    <div className="space-y-4">
      {/* ---- mode columns ---- */}
      <div className="grid grid-cols-2 gap-3">
        {(
          [
            {
              id: 'creative' as const,
              title: 'Creative',
              blurb: 'Hallucinated detail · prompt-guided',
              detail: 'Creativity / Resemblance / Fractality / HDR · categories · prompt',
            },
            {
              id: 'precision' as const,
              title: 'Precision',
              blurb: 'Faithful super-resolution · no invention',
              detail: 'Engine · Sharpness 0–100 · Grain 0–100',
            },
          ]
        ).map((col) => {
          const active = state.mode === col.id;
          return (
            <button
              key={col.id}
              onClick={() => set('mode', col.id)}
              aria-pressed={active}
              className={`text-left rounded-xl border p-4 transition ${
                active
                  ? col.id === 'precision'
                    ? 'border-amber-400 bg-amber-400/10 shadow-lg shadow-amber-950/40'
                    : 'border-sky-400 bg-sky-400/10'
                  : 'border-slate-800 bg-slate-950 hover:border-slate-700'
              }`}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-black uppercase tracking-wide text-slate-100">
                  {col.title}
                </span>
                <span
                  className={`w-3.5 h-3.5 rounded-full border-2 ${
                    active
                      ? col.id === 'precision'
                        ? 'border-amber-400 bg-amber-400'
                        : 'border-sky-400 bg-sky-400'
                      : 'border-slate-600'
                  }`}
                />
              </div>
              <div className="text-xs text-slate-400 mt-1">{col.blurb}</div>
              <div className="text-[11px] text-slate-600 mt-2">{col.detail}</div>
            </button>
          );
        })}
      </div>

      {/* ---- rung grid ---- */}
      <section>
        <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold mb-2">
          Scale rungs · progressive 2→4→8→16 chain
        </h3>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {SCALE_FACTORS.map((s) => {
            const active = state.scale === s;
            const stages = Math.log2(SCALE_INT[s]);
            return (
              <button
                key={s}
                onClick={() => set('scale', s)}
                aria-pressed={active}
                data-testid={`precision-scale-${s}`}
                className={`rounded-xl border p-3 text-left transition ${
                  active
                    ? 'border-amber-400 bg-amber-400/10'
                    : 'border-slate-800 bg-slate-950 hover:border-slate-700'
                }`}
              >
                <div className="text-2xl font-black text-slate-100">{s}</div>
                <div className="text-[11px] font-mono text-slate-400">
                  {SOURCE_WIDTH * SCALE_INT[s]}×{SOURCE_HEIGHT * SCALE_INT[s]}
                </div>
                <div className="text-[10px] text-slate-600 mt-1">
                  {stages} × 2x {stages === 1 ? 'stage' : 'stages'}
                </div>
              </button>
            );
          })}
        </div>
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* ---- engine spec sheet ---- */}
        <section className="border border-slate-800 rounded-xl overflow-hidden">
          <h3 className="text-[11px] uppercase tracking-wider text-slate-500 font-bold px-3 py-2 bg-slate-900 border-b border-slate-800">
            Engine spec sheet
          </h3>
          <table className="w-full text-xs">
            <thead>
              <tr className="text-slate-500 text-left">
                <th className="px-3 py-2 font-semibold">Engine</th>
                <th className="px-3 py-2 font-semibold">Peak VRAM</th>
                <th className="px-3 py-2 font-semibold">Latency</th>
                <th className="px-3 py-2 font-semibold">Pick</th>
              </tr>
            </thead>
            <tbody>
              {ENGINES.map((e) => {
                const active = state.engine === e.id;
                return (
                  <tr
                    key={e.id}
                    onClick={() => set('engine', e.id)}
                    className={`cursor-pointer border-t border-slate-800 ${
                      active ? 'bg-amber-400/10' : 'hover:bg-slate-900'
                    }`}
                  >
                    <td className="px-3 py-2">
                      <div className="font-bold text-slate-100">{e.name}</div>
                      <div className="text-[10px] text-slate-500">{e.hint}</div>
                    </td>
                    <td className="px-3 py-2 font-mono text-slate-400">{e.vram}</td>
                    <td className="px-3 py-2 text-slate-400">{e.latency}</td>
                    <td className="px-3 py-2">
                      <span
                        className={`text-[10px] font-bold ${
                          active ? 'text-amber-300' : 'text-slate-600'
                        }`}
                      >
                        {active ? '● SELECTED' : '○ select'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-3 py-2 text-[10px] text-slate-600 border-t border-slate-800">
            Manual pick (decision 10, #123) — no automatic noise classification in v1.
          </div>
        </section>

        {/* ---- controls ---- */}
        <section className="space-y-3">
          {state.mode === 'precision' ? (
            <>
              <div className="flex items-center gap-2">
                <span className="text-[11px] uppercase tracking-wider text-slate-500 font-bold">
                  Preset
                </span>
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
                    className={`px-3 py-1 rounded-md text-[11px] font-semibold border ${
                      activePreset?.id === p.id
                        ? 'border-amber-400 text-amber-300 bg-amber-400/10'
                        : 'border-slate-800 text-slate-400'
                    }`}
                  >
                    {p.name}
                  </button>
                ))}
                <span className="text-[11px] text-slate-600">
                  {activePreset ? '' : '· custom'}
                </span>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Stepper
                  label="Sharpness"
                  value={state.sharpness}
                  hint="UnsharpMask r2 · percent = value × 1.2"
                  testId="precision-sharpness-value"
                  onChange={(v) =>
                    setState((p) => ({
                      ...p,
                      sharpness: v,
                      preset: PRECISION_PRESETS.find(
                        (x) => x.sharpness === v && x.grain === p.grain
                      )?.id ?? 'custom',
                    }))
                  }
                />
                <Stepper
                  label="Grain"
                  value={state.grain}
                  hint="seeded zero-mean gaussian · σ = value/100 × 12"
                  testId="precision-grain-value"
                  onChange={(v) =>
                    setState((p) => ({
                      ...p,
                      grain: v,
                      preset: PRECISION_PRESETS.find(
                        (x) => x.sharpness === p.sharpness && x.grain === v
                      )?.id ?? 'custom',
                    }))
                  }
                />
              </div>
            </>
          ) : (
            <div className="grid grid-cols-2 gap-3 opacity-75">
              {(
                [
                  ['Creativity', 'creativity'],
                  ['Resemblance', 'resemblance'],
                  ['Fractality', 'fractality'],
                  ['HDR', 'hdr'],
                ] as const
              ).map(([label, key]) => (
                <div key={key} className="border border-slate-800 rounded-lg p-3 bg-slate-950">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      {label}
                    </span>
                    <span className="font-mono text-sm font-bold text-sky-300">
                      {creative[key]}
                    </span>
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
        </section>
      </div>

      <pre
        data-testid="precision-payload"
        className="text-[11px] leading-relaxed font-mono text-emerald-300 bg-slate-950 border border-slate-800 rounded-lg p-3 overflow-x-auto"
      >
        {JSON.stringify(payload, null, 2)}
      </pre>
    </div>
  );
}
