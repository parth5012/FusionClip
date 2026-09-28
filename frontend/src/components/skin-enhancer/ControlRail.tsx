'use client';

import React from 'react';
import { ArrowLeftRight, Cpu, Loader2, Play, Sparkles } from 'lucide-react';
import {
  DEFAULT_SKIN_DETAIL,
  FLEXIBLE_PRESETS,
  MODES,
  resolveSkinDetailMeaning,
  type SkinSettings,
} from '../../utils/skin';
import type { SkinPresetMeta } from '../../utils/skin';

interface ControlRailProps {
  settings: SkinSettings;
  onChange: (patch: Partial<SkinSettings>) => void;
  /** Preset descriptions, preferring the endpoint's own text when it was read. */
  presets?: SkinPresetMeta[];
  /** The endpoint's wording for what skin_detail means in the current mode (#111 decision 2). */
  skinDetailSemantics?: string;
  running: boolean;
  selectedCount: number;
  onRun: () => void;
  onFullscreen: () => void;
  canFullscreen: boolean;
  error: string | null;
}

const SLIDERS: Array<{
  key: 'sharpen' | 'smartGrain' | 'skinDetail';
  label: string;
  note: (mode: SkinSettings['mode']) => string;
}> = [
  { key: 'sharpen', label: 'Sharpen', note: () => 'post-filter · every mode' },
  { key: 'smartGrain', label: 'Smart Grain', note: () => 'post-filter · every mode' },
  {
    key: 'skinDetail',
    label: 'Skin Detail',
    note: (mode) =>
      mode === 'faithful'
        ? `default ${DEFAULT_SKIN_DETAIL} · via post-filter`
        : `default ${DEFAULT_SKIN_DETAIL} · via DiffBIR guidance`,
  },
];

/**
 * B's contribution: the control rail never lies about what a knob does.
 *
 * Every mode row carries its engine and the per-image budget #111 stated, and
 * the amber box names the live meaning of `skin_detail`, because decision 2
 * made it a different physical control per engine.
 */
export default function ControlRail({
  settings,
  onChange,
  presets,
  skinDetailSemantics,
  running,
  selectedCount,
  onRun,
  onFullscreen,
  canFullscreen,
  error,
}: ControlRailProps) {
  const active = MODES.find((m) => m.id === settings.mode) ?? MODES[0];
  const detail = resolveSkinDetailMeaning(settings.mode);
  const presetList = presets && presets.length > 0 ? presets : FLEXIBLE_PRESETS;
  const activePreset = presetList.find((p) => p.id === settings.preset) ?? presetList[0];

  return (
    <div className="space-y-4 p-4" data-testid="skin-control-rail">
      <div className="space-y-1.5">
        {MODES.map((mode) => (
          <button
            key={mode.id}
            type="button"
            data-testid={`skin-mode-${mode.id}`}
            aria-pressed={settings.mode === mode.id}
            disabled={running}
            onClick={() => onChange({ mode: mode.id })}
            className={`w-full rounded-lg border px-3 py-2 text-left transition disabled:cursor-not-allowed disabled:opacity-50 ${
              settings.mode === mode.id
                ? 'border-amber-400 bg-amber-400/10'
                : 'border-slate-800 hover:border-slate-700'
            }`}
          >
            <span className="flex items-baseline justify-between">
              <span className="text-xs font-semibold text-slate-100">{mode.label}</span>
              <span className="inline-flex items-center gap-1.5 font-mono text-[10px] text-slate-400">
                <Cpu className="h-3 w-3" />
                {mode.engine}
                <span className="text-slate-500">{mode.budget}/image</span>
              </span>
            </span>
            <span className="mt-0.5 block text-[11px] text-slate-400">{mode.blurb}</span>
          </button>
        ))}
      </div>

      {settings.mode === 'flexible' && (
        <div className="space-y-1.5">
          <label htmlFor="skin-preset" className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
            Preset
          </label>
          <select
            id="skin-preset"
            data-testid="skin-preset"
            value={settings.preset}
            disabled={running}
            onChange={(e) => onChange({ preset: e.target.value })}
            className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-2 font-mono text-[11px] text-slate-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {presetList.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.label}
              </option>
            ))}
          </select>
          <p className="text-[10px] text-slate-500">{activePreset?.blurb}</p>
        </div>
      )}

      <div
        data-testid="skin-detail-meaning"
        className="rounded border border-amber-500/40 bg-amber-500/5 px-2 py-1.5"
      >
        <p className="font-mono text-[10px] leading-relaxed text-amber-200">
          Skin Detail is driven by <b>{detail.engine}</b> in {active.label} mode.
        </p>
        <p className="font-mono text-[10px] text-amber-300/70">
          meaning: {skinDetailSemantics || detail.meaning}
        </p>
      </div>

      {SLIDERS.map((slider) => (
        <div key={slider.key} className="space-y-1">
          <div className="flex items-baseline justify-between">
            <label htmlFor={`skin-slider-${slider.key}`} className="text-[11px] font-semibold text-slate-300">
              {slider.label}
            </label>
            <span className="font-mono text-[10px] text-sky-400" data-testid={`skin-value-${slider.key}`}>
              {settings[slider.key]}
            </span>
          </div>
          <input
            id={`skin-slider-${slider.key}`}
            type="range"
            min={0}
            max={100}
            step={1}
            value={settings[slider.key]}
            disabled={running}
            onChange={(e) => onChange({ [slider.key]: Number(e.target.value) } as Partial<SkinSettings>)}
            className="w-full accent-amber-400 disabled:cursor-not-allowed disabled:opacity-50"
          />
          <p className="text-[10px] text-slate-500">{slider.note(settings.mode)}</p>
        </div>
      ))}

      {error && (
        <p
          data-testid="skin-run-error"
          className="rounded-md border border-rose-900/50 bg-rose-950/30 px-3 py-2 text-xs text-rose-300"
        >
          {error}
        </p>
      )}

      <button
        type="button"
        data-testid="skin-run"
        onClick={onRun}
        disabled={running || selectedCount === 0}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-amber-400 px-3 py-2.5 text-xs font-semibold text-slate-950 transition hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {running ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
        {running ? 'Enhancing…' : `Enhance ${selectedCount}`.trim()}
      </button>

      <button
        type="button"
        data-testid="skin-fullscreen-compare"
        onClick={onFullscreen}
        disabled={!canFullscreen}
        className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-xs text-slate-300 transition hover:border-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <ArrowLeftRight className="h-3.5 w-3.5" /> Full-screen compare
      </button>
      {!canFullscreen && (
        <p className="flex items-center gap-1.5 text-[10px] text-slate-500">
          <Sparkles className="h-3 w-3" /> Compare unlocks once the focused portrait has a result.
        </p>
      )}
    </div>
  );
}
