'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * VARIANT A — "Portrait Studio"
 * Hypothesis: the before/after comparison IS the product. Give it the room
 * (left ~62% of the panel) and let controls be a quiet right rail.
 * Structure: hero canvas + control rail. No shared layout with B or C.
 */
import React, { useState } from 'react';
import { ArrowLeftRight, Play, Sparkles, Loader2 } from 'lucide-react';
import { FLEXIBLE_PRESETS, INITIAL_SKIN, MODES, PORTRAIT, PORTRAIT_AFTER, SkinMode, SkinState, clamp, skinDetailMeaning } from './types';

export default function VariantA() {
  const [s, setS] = useState<SkinState>(INITIAL_SKIN);
  const [split, setSplit] = useState(50);
  const [running, setRunning] = useState(false);
  const [face, setFace] = useState(1);
  const [faces, setFaces] = useState(1);

  const set = (k: keyof SkinState, v: string | number) => setS((p) => ({ ...p, [k]: v }));
  const detail = skinDetailMeaning(s.mode);

  const run = () => {
    setRunning(true);
    setFaces(3);
    let i = 1;
    const t = setInterval(() => {
      i += 1;
      setFace(i);
      if (i >= 3) {
        clearInterval(t);
        setRunning(false);
      }
    }, 700);
  };

  return (
    <div className="rounded-xl border border-amber-500/30 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-300" />
          <span className="text-xs font-semibold text-slate-100">Skin Enhancer — Portrait Studio</span>
        </div>
        <span className="font-mono text-[10px] text-slate-500">PROTOTYPE A</span>
      </div>

      <div className="grid grid-cols-1 gap-0 lg:grid-cols-[1.6fr_1fr]">
        {/* Hero: the comparison gets the space. */}
        <div className="relative border-b border-slate-800 lg:border-b-0 lg:border-r">
          <div className="relative aspect-[4/5] max-h-[30rem] w-full overflow-hidden bg-slate-950 select-none">
            <img src={PORTRAIT_AFTER} alt="after" className="absolute inset-0 h-full w-full object-cover" />
            <div className="absolute inset-0 overflow-hidden" style={{ width: `${split}%` }}>
              <img src={PORTRAIT} alt="before" className="h-full w-full object-cover" style={{ maxWidth: 'none' }} />
            </div>
            <div className="absolute top-0 bottom-0 w-0.5 bg-amber-300/90" style={{ left: `${split}%` }}>
              <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-7 w-7 rounded-full bg-amber-300 text-slate-900 grid place-items-center text-[10px] font-bold">
                ↔
              </div>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={split}
              onChange={(e) => setSplit(Number(e.target.value))}
              className="absolute inset-x-0 bottom-0 h-1 cursor-ew-resize opacity-0"
              aria-label="Before/after split"
            />
            <span className="absolute left-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">before</span>
            <span className="absolute right-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">after</span>
            {running && (
              <div className="absolute inset-x-0 bottom-0 bg-slate-950/85 px-3 py-2">
                <div className="mb-1 flex justify-between font-mono text-[10px] text-amber-200">
                  <span>Enhancing face {face} of {faces}…</span>
                  <span>{MODES.find((m) => m.id === s.mode)?.budget}</span>
                </div>
                <div className="h-1 rounded bg-slate-700">
                  <div className="h-1 rounded bg-amber-400" style={{ width: `${(face / faces) * 100}%` }} />
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Quiet right rail. */}
        <div className="space-y-5 p-4">
          <div className="space-y-2">
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => set('mode', m.id as SkinMode)}
                className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                  s.mode === m.id ? 'border-amber-400 bg-amber-400/10' : 'border-slate-700 hover:border-slate-600'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-100">{m.label}</span>
                  <span className="font-mono text-[10px] text-slate-500">{m.budget}</span>
                </div>
                <p className="mt-0.5 text-[11px] text-slate-400">{m.blurb}</p>
              </button>
            ))}
          </div>

          {s.mode === 'flexible' && (
            <div className="space-y-1.5">
              <label className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Preset</label>
              <select
                value={s.preset}
                onChange={(e) => set('preset', e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 text-xs text-slate-200"
              >
                {FLEXIBLE_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-500">
                {FLEXIBLE_PRESETS.find((p) => p.id === s.preset)?.blurb}
              </p>
            </div>
          )}

          {(['sharpen', 'smartGrain', 'skinDetail'] as const).map((k) => {
            const label = k === 'sharpen' ? 'Sharpen' : k === 'smartGrain' ? 'Smart Grain' : 'Skin Detail';
            return (
              <div key={k} className="space-y-1">
                <div className="flex items-baseline justify-between">
                  <span className="text-[11px] font-semibold text-slate-300">{label}</span>
                  <span className="font-mono text-[10px] text-sky-400">{s[k]}</span>
                </div>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={s[k]}
                  onChange={(e) => set(k, clamp(Number(e.target.value)))}
                  className="w-full accent-amber-400"
                />
                {k === 'skinDetail' && (
                  <p className="font-mono text-[10px] text-amber-300/80">
                    via {detail.engine} — {detail.meaning}
                  </p>
                )}
              </div>
            );
          })}

          <button
            onClick={run}
            disabled={running}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-400 px-3 py-2.5 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-50"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Enhancing…' : 'Enhance portrait'}
          </button>

          <button className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-slate-600">
            <ArrowLeftRight className="h-3.5 w-3.5" /> Full-screen compare
          </button>
        </div>
      </div>
    </div>
  );
}
