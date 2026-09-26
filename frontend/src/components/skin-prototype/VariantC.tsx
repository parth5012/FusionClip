'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * VARIANT C — "Batch Queue"
 * Hypothesis: this is a tool you point at a folder of portraits, not a panel
 * you fiddle with one image at a time. No live preview at all — you pick
 * sources, hit go once, and judge each result in a tray afterwards.
 * Mirrors the shipped upscaler's bulk queue. Structure: picker strip on top,
 * a single compact control bar, results tray below. No sliders column, no
 * hero canvas.
 */
import React, { useState } from 'react';
import { Play, Loader2, CheckCircle2, X, FolderOpen } from 'lucide-react';
import { FLEXIBLE_PRESETS, INITIAL_SKIN, MODES, PORTRAIT, PORTRAIT_B, PORTRAIT_AFTER, PORTRAIT_B_AFTER, SkinMode, SkinState } from './types';

interface Item {
  id: string;
  name: string;
  before: string;
  after: string;
  status: 'queued' | 'running' | 'done';
  step?: string;
  pct: number;
}

const INITIAL: Item[] = [
  { id: '1', name: 'portrait_0042.jpg', before: PORTRAIT, after: PORTRAIT_AFTER, status: 'queued', pct: 0 },
  { id: '2', name: 'headshot_0117.jpg', before: PORTRAIT_B, after: PORTRAIT_B_AFTER, status: 'queued', pct: 0 },
  { id: '3', name: 'press_closeup.jpg', before: PORTRAIT, after: PORTRAIT_AFTER, status: 'queued', pct: 0 },
];

export default function VariantC() {
  const [s, setS] = useState<SkinState>(INITIAL_SKIN);
  const [items, setItems] = useState<Item[]>(INITIAL);
  const [picked, setPicked] = useState<string[]>(['1', '2']);

  const set = (k: keyof SkinState, v: string | number) => setS((p) => ({ ...p, [k]: v }));
  const active = MODES.find((m) => m.id === s.mode)!;
  const queued = items.filter((i) => picked.includes(i.id));

  const toggle = (id: string) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));

  const run = () => {
    setItems((prev) => prev.map((i) => (picked.includes(i.id) ? { ...i, status: 'running', pct: 0 } : i)));
    let idx = 0;
    const targets = queued;
    const t = setInterval(() => {
      idx += 1;
      setItems((prev) =>
        prev.map((i) => {
          if (!targets.find((x) => x.id === i.id)) return i;
          const pos = targets.findIndex((x) => x.id === i.id);
          if (pos > idx) return { ...i, status: 'running', pct: 0, step: 'queued' };
          if (pos < idx) return { ...i, status: 'done', pct: 100 };
          return { ...i, status: 'running', pct: 55, step: 'face 1 of 2' };
        }),
      );
      if (idx >= targets.length + 1) {
        clearInterval(t);
        setItems((prev) =>
          prev.map((i) => (picked.includes(i.id) ? { ...i, status: 'done', pct: 100 } : i)),
        );
      }
    }, 650);
  };

  return (
    <div className="rounded-xl border border-amber-500/30 bg-slate-900/40">
      <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2">
        <div className="flex items-center gap-2">
          <FolderOpen className="h-4 w-4 text-amber-300" />
          <span className="text-xs font-semibold text-slate-100">Skin Enhancer — Batch Queue</span>
        </div>
        <span className="font-mono text-[10px] text-slate-500">PROTOTYPE C</span>
      </div>

      {/* 1. Sources. */}
      <div className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-[11px] uppercase tracking-wide text-slate-400">Portraits</span>
          <span className="font-mono text-[10px] text-slate-500">{picked.length} selected</span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {items.map((it) => {
            const on = picked.includes(it.id);
            return (
              <button
                key={it.id}
                onClick={() => toggle(it.id)}
                className={`group relative overflow-hidden rounded-lg border text-left ${
                  on ? 'border-amber-400 ring-1 ring-amber-400/50' : 'border-slate-800 hover:border-slate-700'
                }`}
              >
                <img src={it.before} alt="" className="aspect-square w-full object-cover opacity-80" />
                <span className="absolute inset-x-0 bottom-0 truncate bg-slate-950/85 px-1.5 py-1 font-mono text-[9px] text-slate-300">
                  {it.name}
                </span>
                <span
                  className={`absolute right-1 top-1 h-3.5 w-3.5 rounded-full border-2 ${
                    on ? 'border-amber-400 bg-amber-400' : 'border-slate-500'
                  }`}
                />
              </button>
            );
          })}
        </div>
      </div>

      {/* 2. One compact control bar — no slider column. */}
      <div className="flex flex-wrap items-end gap-4 border-y border-slate-800 bg-slate-950/40 px-4 py-3">
        <div>
          <span className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">Mode</span>
          <div className="flex rounded-lg border border-slate-700 p-0.5">
            {MODES.map((m) => (
              <button
                key={m.id}
                onClick={() => set('mode', m.id as SkinMode)}
                className={`rounded-md px-2.5 py-1 text-[11px] ${
                  s.mode === m.id ? 'bg-amber-400 text-slate-950 font-semibold' : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>

        {s.mode === 'flexible' && (
          <div>
            <span className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">Preset</span>
            <select
              value={s.preset}
              onChange={(e) => set('preset', e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 font-mono text-[11px] text-slate-200"
            >
              {FLEXIBLE_PRESETS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="min-w-[13rem] flex-1">
          <span className="mb-1 block text-[10px] uppercase tracking-wide text-slate-500">
            Sharpen <span className="font-mono text-sky-400">{s.sharpen}</span> · Smart Grain{' '}
            <span className="font-mono text-sky-400">{s.smartGrain}</span> · Skin Detail{' '}
            <span className="font-mono text-sky-400">{s.skinDetail}</span>
          </span>
          <div className="flex gap-1">
            {(['sharpen', 'smartGrain', 'skinDetail'] as const).map((k) => (
              <input
                key={k}
                type="range"
                min={0}
                max={100}
                value={s[k]}
                onChange={(e) => set(k, Number(e.target.value))}
                className="w-full accent-amber-400"
                aria-label={k}
              />
            ))}
          </div>
        </div>

        <button
          onClick={run}
          disabled={picked.length === 0}
          className="flex items-center gap-2 rounded-lg bg-amber-400 px-4 py-2 text-xs font-semibold text-slate-950 hover:bg-amber-300 disabled:opacity-40"
        >
          {items.some((i) => i.status === 'running') ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          Enhance {picked.length}
        </button>
      </div>

      {/* 3. Results tray. */}
      <div className="p-4">
        <span className="mb-2 block text-[11px] uppercase tracking-wide text-slate-400">
          Results <span className="font-mono text-slate-500">({active.engine} · {active.budget}/image)</span>
        </span>
        <div className="space-y-1.5">
          {items
            .filter((i) => picked.includes(i.id))
            .map((it) => (
              <div key={it.id} className="flex items-center gap-3 rounded-lg border border-slate-800 px-2.5 py-2">
                <span className="font-mono text-[10px] text-slate-400 w-6">{it.id}</span>
                {it.status === 'done' ? (
                  <img src={it.after} alt="" className="h-9 w-9 rounded object-cover" />
                ) : (
                  <img src={it.before} alt="" className="h-9 w-9 rounded object-cover opacity-50" />
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[11px] text-slate-200">{it.name}</p>
                  {it.status === 'running' && (
                    <div className="mt-1 h-1 rounded bg-slate-700">
                      <div className="h-1 rounded bg-amber-400" style={{ width: `${it.pct}%` }} />
                    </div>
                  )}
                </div>
                <span className="font-mono text-[10px] text-slate-500">
                  {it.status === 'done' ? (
                    <span className="inline-flex items-center gap-1 text-emerald-300">
                      <CheckCircle2 className="h-3 w-3" /> done
                    </span>
                  ) : it.status === 'running' ? (
                    it.step
                  ) : (
                    'queued'
                  )}
                </span>
                <button className="text-slate-600 hover:text-rose-300" aria-label="Remove">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
