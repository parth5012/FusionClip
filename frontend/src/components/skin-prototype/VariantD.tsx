'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * VARIANT D — the composite the human assembled:
 *   A's hero before/after canvas  +  B's engine labels & honest-knob box  +  C's multi-select.
 *
 * Design consequence worth stating: with N sources selected there is no longer
 * one image, so the canvas needs an explicit "focused" item and the results
 * tray becomes the way to move focus. Sliders apply to every selected source
 * (set once, run N) rather than per-image.
 */
import React, { useState } from 'react';
import { Play, Loader2, Cpu, ArrowLeftRight, CheckCircle2, Sparkles } from 'lucide-react';
import {
  FLEXIBLE_PRESETS,
  INITIAL_SKIN,
  MODES,
  PORTRAIT,
  PORTRAIT_AFTER,
  PORTRAIT_B,
  PORTRAIT_B_AFTER,
  SkinMode,
  SkinState,
  clamp,
  skinDetailMeaning,
} from './types';

interface Item {
  id: string;
  name: string;
  before: string;
  after: string;
  status: 'queued' | 'running' | 'done';
  pct: number;
  face: number;
  faces: number;
}

const INITIAL: Item[] = [
  { id: '1', name: 'portrait_0042.jpg', before: PORTRAIT, after: PORTRAIT_AFTER, status: 'queued', pct: 0, face: 0, faces: 3 },
  { id: '2', name: 'headshot_0117.jpg', before: PORTRAIT_B, after: PORTRAIT_B_AFTER, status: 'queued', pct: 0, face: 0, faces: 1 },
  { id: '3', name: 'press_closeup.jpg', before: PORTRAIT, after: PORTRAIT_AFTER, status: 'queued', pct: 0, face: 0, faces: 1 },
];

export default function VariantD() {
  const [s, setS] = useState<SkinState>(INITIAL_SKIN);
  const [items, setItems] = useState<Item[]>(INITIAL);
  const [picked, setPicked] = useState<string[]>(['1', '2']);
  const [focused, setFocused] = useState<string>('1');
  const [split, setSplit] = useState(50);
  const [badValue, setBadValue] = useState<string | null>(null);

  const set = (k: keyof SkinState, v: string | number) => setS((p) => ({ ...p, [k]: v }));
  const active = MODES.find((m) => m.id === s.mode)!;
  const detail = skinDetailMeaning(s.mode);
  const targets = items.filter((i) => picked.includes(i.id));
  const shown = items.find((i) => i.id === focused) ?? items[0];
  const running = items.some((i) => i.status === 'running');

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const run = () => {
    setItems((prev) =>
      prev.map((i) => (picked.includes(i.id) ? { ...i, status: 'running', pct: 0, face: 1 } : i)),
    );
    let tick = 0;
    const t = setInterval(() => {
      tick += 1;
      setItems((prev) =>
        prev.map((i) => {
          if (!picked.includes(i.id)) return i;
          const k = tick % Math.max(targets.length, 1);
          return { ...i, pct: Math.min(95, i.pct + 18), face: Math.min(i.faces, 1 + (tick % Math.max(i.faces, 1))) };
        }),
      );
      if (tick >= 8) {
        clearInterval(t);
        setItems((prev) => prev.map((i) => (picked.includes(i.id) ? { ...i, status: 'done', pct: 100, face: i.faces } : i)));
      }
    }, 420);
  };

  const poke = () => {
    setBadValue('sharpen');
    setTimeout(() => setBadValue(null), 2800);
  };

  return (
    <div className="rounded-xl border border-amber-500/30 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-300" />
          <span className="text-xs font-semibold text-slate-100">Skin Enhancer</span>
          <span className="rounded bg-amber-400/10 px-1.5 py-0.5 font-mono text-[9px] text-amber-300 ring-1 ring-amber-400/30">
            A canvas · B labels · C multi-select
          </span>
        </div>
        <span className="font-mono text-[10px] text-slate-500">PROTOTYPE D</span>
      </div>

      {/* C's multi-select strip. */}
      <div className="flex items-center gap-2 overflow-x-auto border-b border-slate-800 px-4 py-3">
        {items.map((it) => {
          const on = picked.includes(it.id);
          const isFocus = focused === it.id;
          return (
            <button
              key={it.id}
              onClick={() => (on ? setFocused(it.id) : toggle(it.id))}
              onDoubleClick={() => toggle(it.id)}
              title={on ? 'Click to focus · double-click to unselect' : 'Click to select'}
              className={`relative shrink-0 overflow-hidden rounded-lg border-2 transition ${
                isFocus ? 'border-sky-400' : on ? 'border-amber-400' : 'border-slate-800 opacity-60 hover:opacity-100'
              }`}
            >
              <img src={it.status === 'done' ? it.after : it.before} alt="" className="h-14 w-14 object-cover" />
              {it.status === 'running' && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-slate-700">
                  <span className="block h-0.5 bg-amber-400" style={{ width: `${it.pct}%` }} />
                </span>
              )}
              <span
                className={`absolute -right-1 -top-1 h-3.5 w-3.5 rounded-full border-2 text-[8px] leading-[10px] ${
                  on ? 'border-amber-400 bg-amber-400 text-slate-950' : 'border-slate-600 bg-slate-950'
                }`}
              >
                {on ? '✓' : ''}
              </span>
            </button>
          );
        })}
        <span className="ml-1 shrink-0 font-mono text-[10px] text-slate-500">
          {picked.length} selected · click a thumb to focus
        </span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-[1.55fr_1fr]">
        {/* A's hero canvas. */}
        <div className="border-b border-slate-800 lg:border-b-0 lg:border-r">
          <div className="relative aspect-[4/5] max-h-[27rem] w-full overflow-hidden bg-slate-950 select-none">
            <img src={shown.after} alt="after" className="absolute inset-0 h-full w-full object-cover" />
            <div className="absolute inset-y-0 left-0 overflow-hidden" style={{ width: `${split}%` }}>
              <img src={shown.before} alt="before" className="h-full object-cover" style={{ width: `${100 / (split / 100)}%` }} />
            </div>
            <div className="absolute inset-y-0 w-0.5 bg-amber-300/90" style={{ left: `${split}%` }}>
              <div className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 grid h-7 w-7 place-items-center rounded-full bg-amber-300 text-[10px] font-bold text-slate-900">
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
              aria-label="Before after split"
            />
            <span className="absolute left-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">before</span>
            <span className="absolute right-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
              {shown.status === 'done' ? 'after' : 'preview'}
            </span>
            <span className="absolute left-2 top-8 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
              {shown.name}
            </span>

            {shown.status === 'running' && (
              <div className="absolute inset-x-0 bottom-0 bg-slate-950/85 px-3 py-2">
                <div className="mb-1 flex justify-between font-mono text-[10px] text-amber-200">
                  <span>
                    Enhancing face {shown.face} of {shown.faces} · {active.engine}
                  </span>
                  <span>{active.budget}/image</span>
                </div>
                <div className="h-1 rounded bg-slate-700">
                  <div className="h-1 rounded bg-amber-400" style={{ width: `${shown.pct}%` }} />
                </div>
              </div>
            )}
          </div>

          {/* C's results tray, demoted to a strip under the canvas. */}
          <div className="space-y-1 p-3">
            {targets.map((it) => (
              <button
                key={it.id}
                onClick={() => setFocused(it.id)}
                className={`flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-1.5 text-left ${
                  focused === it.id ? 'border-sky-500/60 bg-sky-500/5' : 'border-slate-800 hover:border-slate-700'
                }`}
              >
                {it.status === 'done' ? (
                  <img src={it.after} alt="" className="h-7 w-7 rounded object-cover" />
                ) : (
                  <img src={it.before} alt="" className="h-7 w-7 rounded object-cover opacity-50" />
                )}
                <span className="min-w-0 flex-1 truncate text-[11px] text-slate-300">{it.name}</span>
                <span className="font-mono text-[10px] text-slate-500">
                  {it.status === 'done' ? (
                    <span className="inline-flex items-center gap-1 text-emerald-300">
                      <CheckCircle2 className="h-3 w-3" /> done
                    </span>
                  ) : it.status === 'running' ? (
                    `face ${it.face}/${it.faces}`
                  ) : (
                    'queued'
                  )}
                </span>
              </button>
            ))}
          </div>
        </div>

        {/* B's engine-transparent control rail, on A's rail. */}
        <div className="space-y-4 p-4">
          <div className="space-y-1.5">
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => set('mode', m.id as SkinMode)}
                className={`w-full rounded-lg border px-3 py-2 text-left transition ${
                  s.mode === m.id ? 'border-amber-400 bg-amber-400/10' : 'border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-baseline justify-between">
                  <span className="text-xs font-semibold text-slate-100">{m.label}</span>
                  <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-slate-400">
                    <Cpu className="h-3 w-3" />
                    {m.engine}
                    <span className="text-slate-500">{m.budget}</span>
                  </span>
                </div>
                <p className="mt-0.5 text-[11px] text-slate-400">{m.blurb}</p>
              </button>
            ))}
          </div>

          {s.mode === 'flexible' && (
            <div className="space-y-1.5">
              <label className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">Preset</label>
              <select
                value={s.preset}
                onChange={(e) => set('preset', e.target.value)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-[11px] text-slate-200"
              >
                {FLEXIBLE_PRESETS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
              <p className="text-[10px] text-slate-500">
                {FLEXIBLE_PRESETS.find((p) => p.id === s.preset)?.blurb}
              </p>
            </div>
          )}

          {/* B's honest-knob box. */}
          <div className="rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1.5">
            <p className="font-mono text-[10px] leading-relaxed text-amber-200">
              Skin Detail is driven by <b>{detail.engine}</b> in {active.label} mode.
            </p>
            <p className="font-mono text-[10px] text-amber-300/70">meaning: {detail.meaning}</p>
          </div>

          {(['sharpen', 'smartGrain', 'skinDetail'] as const).map((k) => {
            const label = k === 'sharpen' ? 'Sharpen' : k === 'smartGrain' ? 'Smart Grain' : 'Skin Detail';
            const note = k === 'skinDetail' ? `default 80 · via ${detail.engine}` : 'post-filter · every mode';
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
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-500">{note}</span>
                  {badValue === k && <span className="font-mono text-[10px] text-rose-400">400 · not clamped</span>}
                </div>
              </div>
            );
          })}
          <button
            onClick={poke}
            className="text-[10px] text-slate-600 underline decoration-dotted hover:text-slate-400"
          >
            simulate sharpen=999
          </button>

          <button
            onClick={run}
            disabled={picked.length === 0 || running}
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-400 px-3 py-2.5 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-40"
          >
            {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {running ? 'Enhancing…' : `Enhance ${picked.length || ''}`.trim()}
          </button>

          <button className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 hover:border-slate-600">
            <ArrowLeftRight className="h-3.5 w-3.5" /> Full-screen compare
          </button>
        </div>
      </div>
    </div>
  );
}
