'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * VARIANT B — "Honest Knob"
 * Hypothesis: the user is about to be lied to by a slider whose meaning
 * changes with the mode (#111 decision 2). So lead with the *meaning* and the
 * engine that will actually run, and treat the preview as secondary.
 * Structure: full-height control column on the left, preview strip on the
 * right. Deliberately not a card grid and not a hero canvas.
 */
import React, { useState } from 'react';
import { Info, Play, Cpu, Loader2, AlertTriangle } from 'lucide-react';
import { FLEXIBLE_PRESETS, INITIAL_SKIN, MODES, PORTRAIT, PORTRAIT_AFTER, SkinMode, SkinState, clamp, skinDetailMeaning } from './types';

export default function VariantB() {
  const [s, setS] = useState<SkinState>(INITIAL_SKIN);
  const [running, setRunning] = useState(false);
  const [showMeaning, setShowMeaning] = useState(true);
  const [outOfRange, setOutOfRange] = useState<string | null>(null);

  const set = (k: keyof SkinState, v: string | number) => setS((p) => ({ ...p, [k]: v }));
  const active = MODES.find((m) => m.id === s.mode)!;
  const detail = skinDetailMeaning(s.mode);

  // #111 decision 4: 400, never a silent clamp. Simulate a bad value.
  const poke = (k: keyof SkinState) => {
    setOutOfRange(k);
    setTimeout(() => setOutOfRange(null), 2600);
  };

  const run = () => {
    setRunning(true);
    setTimeout(() => setRunning(false), 2200);
  };

  const Row = ({ k, label, note }: { k: 'sharpen' | 'smartGrain' | 'skinDetail'; label: string; note: string }) => (
    <div className="border-b border-slate-800 pb-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold text-slate-200">{label}</span>
        <span className="font-mono text-xs text-sky-400">{s[k]}</span>
      </div>
      <input
        type="range"
        min={0}
        max={100}
        value={s[k]}
        onChange={(e) => set(k, clamp(Number(e.target.value)))}
        className="mt-1 w-full accent-amber-400"
      />
      <div className="mt-0.5 flex items-center justify-between">
        <span className="text-[10px] text-slate-500">{note}</span>
        {outOfRange === k && <span className="font-mono text-[10px] text-rose-400">400 clamped</span>}
      </div>
    </div>
  );

  return (
    <div className="overflow-hidden rounded-xl border border-amber-500/30 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <span className="text-xs font-semibold text-slate-100">Skin Enhancer — Honest Knob</span>
        <span className="font-mono text-[10px] text-slate-500">PROTOTYPE B</span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[1.15fr_1fr]">
        {/* Controls lead. */}
        <div className="space-y-4 border-b border-slate-800 p-4 md:border-b-0 md:border-r">
          <div>
            <div className="mb-1.5 flex items-center gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Mode</span>
              <button
                onClick={() => setShowMeaning((v) => !v)}
                title="Toggle explanations"
                className={`rounded p-0.5 ${showMeaning ? 'text-amber-300' : 'text-slate-600'}`}
              >
                <Info className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="space-y-1.5">
              {MODES.map((m) => (
                <label
                  key={m.id}
                  className={`flex cursor-pointer items-start gap-2.5 rounded-lg border px-3 py-2 ${
                    s.mode === m.id ? 'border-amber-400 bg-amber-400/10' : 'border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <input
                    type="radio"
                    name="skin-mode"
                    checked={s.mode === m.id}
                    onChange={() => set('mode', m.id as SkinMode)}
                    className="mt-0.5 accent-amber-400"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between">
                      <span className="text-xs font-semibold text-slate-100">{m.label}</span>
                      <span className="inline-flex items-center gap-1 font-mono text-[10px] text-slate-400">
                        <Cpu className="h-3 w-3" />
                        {m.engine}
                      </span>
                    </span>
                    {showMeaning && <span className="mt-0.5 block text-[11px] text-slate-400">{m.blurb}</span>}
                    {showMeaning && <span className="font-mono text-[10px] text-slate-500">budget {m.budget} per image</span>}
                  </span>
                </label>
              ))}
            </div>
          </div>

          {s.mode === 'flexible' && (
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">Preset</span>
              <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                {FLEXIBLE_PRESETS.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => set('preset', p.id)}
                    title={p.blurb}
                    className={`truncate rounded border px-2 py-1.5 text-left font-mono text-[10px] ${
                      s.preset === p.id
                        ? 'border-amber-400 bg-amber-400/10 text-amber-200'
                        : 'border-slate-800 text-slate-400 hover:border-slate-700'
                    }`}
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <p className="mt-1 text-[10px] text-slate-500">
                {FLEXIBLE_PRESETS.find((p) => p.id === s.preset)?.blurb}
              </p>
            </div>
          )}

          <div>
            <Row k="sharpen" label="Sharpen" note="post-filter · every mode" />
            <div className="pt-3">
              <Row k="smartGrain" label="Smart Grain" note="post-filter · every mode" />
            </div>
            <div className="pt-3">
              <div className="mb-1 rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1.5">
                <p className="font-mono text-[10px] leading-relaxed text-amber-200">
                  Skin Detail is driven by <b>{detail.engine}</b> in {active.label} mode.
                </p>
                <p className="font-mono text-[10px] text-amber-300/70">meaning: {detail.meaning}</p>
              </div>
              <Row k="skinDetail" label="Skin Detail" note={`default 80 · via ${detail.engine}`} />
            </div>
            <button
              onClick={() => poke('sharpen')}
              className="mt-2 text-[10px] text-slate-600 underline decoration-dotted hover:text-slate-400"
            >
              simulate sharpen=999 (see the 400, not a silent clamp)
            </button>
          </div>

          <button
            onClick={run}
            disabled={running}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-400 px-3 py-2.5 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-50"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? `Running ${active.engine}…` : 'Enhance portrait'}
          </button>
        </div>

        {/* Preview is secondary and deliberately small. */}
        <div className="flex flex-col p-4">
          <p className="mb-2 text-[11px] uppercase tracking-wide text-slate-500">Result preview</p>
          <div className="relative aspect-square w-full overflow-hidden rounded-lg bg-slate-950 ring-1 ring-slate-800">
            <img src={PORTRAIT_AFTER} alt="after" className="absolute inset-0 h-full w-full object-cover" />
            <div className="absolute bottom-0 left-0 right-0 flex items-center justify-between bg-slate-950/85 px-2 py-1">
              <span className="font-mono text-[10px] text-emerald-300">{active.engine}</span>
              <span className="font-mono text-[10px] text-slate-400">{running ? 'running…' : `${active.budget}`}</span>
            </div>
          </div>
          <p className="mt-2 text-[10px] text-slate-500">
            source: {PORTRAIT.slice(0, 46)}…
          </p>
          <div className="mt-3 flex items-start gap-1.5 rounded border border-rose-500/30 bg-rose-500/5 px-2 py-1.5">
            <AlertTriangle className="mt-px h-3 w-3 shrink-0 text-rose-300" />
            <p className="text-[10px] leading-relaxed text-rose-200/90">
              {active.label} alters facial geometry. Compare before accepting.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
