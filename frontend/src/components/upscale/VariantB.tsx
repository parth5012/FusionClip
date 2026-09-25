'use client';

import React, { useState } from 'react';
import CompareSlider from './CompareSlider';
import {
  ScaleFactor,
  PresetType,
  ContentCategory,
  SliderValues,
  PRESET_RECIPES,
  CATEGORIES,
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
} from './types';
import {
  Sparkles,
  Sliders,
  Layers,
  Wand2,
  X,
  Play,
  RotateCcw,
  SlidersHorizontal,
  ChevronDown,
  Info,
} from 'lucide-react';

export default function VariantB() {
  const [scale, setScale] = useState<ScaleFactor>('4x');
  const [preset, setPreset] = useState<PresetType>('vivid');
  const [category, setCategory] = useState<ContentCategory>('universal');
  const [sliders, setSliders] = useState<SliderValues>(PRESET_RECIPES.vivid.sliders);
  const [prompt, setPrompt] = useState('');
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [selectedSample, setSelectedSample] = useState(0);

  const samples = [
    {
      title: 'Studio Portrait',
      before: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=40',
      after: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=2400&q=95',
      dim: '512×512',
    },
    {
      title: 'Tokyo Street Night',
      before: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=600&q=40',
      after: 'https://images.unsplash.com/photo-1503899036084-c55cdd92da26?auto=format&fit=crop&w=2400&q=95',
      dim: '640×420',
    },
    {
      title: 'Alpine Peak',
      before: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=600&q=40',
      after: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?auto=format&fit=crop&w=2400&q=95',
      dim: '720×480',
    },
  ];

  const handlePresetSelect = (p: PresetType) => {
    setPreset(p);
    setSliders(PRESET_RECIPES[p].sliders);
  };

  const handleSliderChange = (key: keyof SliderValues, value: number) => {
    setSliders((prev) => ({ ...prev, [key]: value }));
    setPreset('custom');
  };

  return (
    <div className="relative space-y-4">
      {/* Top HUD Floating Control Bar */}
      <div className="flex items-center justify-between gap-3 p-3 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-xl backdrop-blur-md">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-sky-500/20 text-sky-400 rounded-xl">
            <Sparkles className="w-5 h-5" />
          </div>
          <div>
            <div className="font-bold text-sm text-white flex items-center gap-2">
              Magnific HUD
              <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-950/70 border border-indigo-800 text-indigo-300">
                Variant B: Canvas HUD
              </span>
            </div>
            <div className="text-[11px] text-slate-400">Full-bleed canvas with quick presets</div>
          </div>
        </div>

        {/* Quick presets pills */}
        <div className="hidden md:flex items-center gap-1.5 bg-slate-950/70 p-1 rounded-xl border border-slate-800">
          {(['subtle', 'vivid', 'wild'] as PresetType[]).map((p) => (
            <button
              key={p}
              onClick={() => handlePresetSelect(p)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold capitalize transition ${
                preset === p
                  ? 'bg-sky-500 text-slate-950 shadow-sm'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {p}
            </button>
          ))}
        </div>

        {/* Scale buttons */}
        <div className="flex items-center gap-1 bg-slate-950/70 p-1 rounded-xl border border-slate-800">
          {(['2x', '4x', '8x'] as ScaleFactor[]).map((s) => (
            <button
              key={s}
              onClick={() => setScale(s)}
              className={`px-2.5 py-1 rounded-lg text-xs font-bold transition ${
                scale === s ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              {s}
            </button>
          ))}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setInspectorOpen(true)}
            className={`p-2 rounded-xl border text-xs font-medium transition flex items-center gap-1.5 ${
              inspectorOpen
                ? 'bg-sky-500 text-slate-950 border-sky-400 font-bold'
                : 'bg-slate-800 border-slate-700 text-slate-300 hover:text-white'
            }`}
            title="Open Parameter Inspector"
          >
            <SlidersHorizontal className="w-4 h-4" />
            <span className="hidden sm:inline">Sliders</span>
          </button>

          <button className="px-4 py-2 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white rounded-xl text-xs font-bold shadow-lg shadow-sky-500/20 flex items-center gap-1.5 transition">
            <Play className="w-3.5 h-3.5 fill-current" />
            Upscale {scale}
          </button>
        </div>
      </div>

      {/* Main Full-Bleed Canvas */}
      <div className="relative">
        <CompareSlider
          beforeUrl={samples[selectedSample].before}
          afterUrl={samples[selectedSample].after}
          beforeLabel={`Original (${samples[selectedSample].dim})`}
          afterLabel={`${samples[selectedSample].title} • ${scale} SDXL-Tile (${preset})`}
          aspectRatio="aspect-[16/9]"
          className="min-h-[460px]"
        />

        {/* Floating Bottom Filmstrip */}
        <div className="absolute bottom-4 left-4 right-4 z-20 flex items-center justify-between p-2 bg-slate-950/80 border border-slate-800/80 rounded-xl backdrop-blur-md">
          <div className="flex items-center gap-2 overflow-x-auto">
            <span className="text-[11px] font-semibold text-slate-400 px-2 flex-shrink-0">
              Sample Assets:
            </span>
            {samples.map((s, idx) => (
              <button
                key={s.title}
                onClick={() => setSelectedSample(idx)}
                className={`flex items-center gap-2 p-1.5 rounded-lg border text-xs transition flex-shrink-0 ${
                  selectedSample === idx
                    ? 'bg-sky-950/80 border-sky-500 text-white'
                    : 'bg-slate-900 border-slate-800 text-slate-400 hover:text-slate-200'
                }`}
              >
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={s.before} alt={s.title} className="w-6 h-6 rounded object-cover" />
                <span className="text-[11px] font-medium">{s.title}</span>
              </button>
            ))}
          </div>

          <div className="text-[11px] text-slate-400 font-mono hidden md:block">
            Creativity: {sliders.creativity > 0 ? `+${sliders.creativity}` : sliders.creativity} •
            Resemblance: {sliders.resemblance > 0 ? `+${sliders.resemblance}` : sliders.resemblance}
          </div>
        </div>
      </div>

      {/* Slide-Over Inspector Drawer */}
      {inspectorOpen && (
        <aside aria-label="Fine-grained parameter controls" className="fixed inset-y-0 right-0 z-50 w-96 bg-slate-900/98 border-l border-slate-800 shadow-2xl p-6 flex flex-col justify-between backdrop-blur-xl animate-in slide-in-from-right duration-200">
          <div className="space-y-6 overflow-y-auto pr-1">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <h3 className="font-bold text-sm text-white flex items-center gap-2">
                <Sliders className="w-4 h-4 text-sky-400" />
                Parameter Inspector
              </h3>
              <button
                onClick={() => setInspectorOpen(false)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Category */}
            <div className="space-y-2">
              <label className="text-xs font-semibold text-slate-300">Category Modifier</label>
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as ContentCategory)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                {CATEGORIES.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Sliders (-10..+10) */}
            <div className="space-y-4">
              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Creativity (Denoise)</span>
                  <span className="font-mono text-sky-400 font-bold">
                    {sliders.creativity > 0 ? `+${sliders.creativity}` : sliders.creativity}
                  </span>
                </div>
                <input
                  type="range"
                  min={-10}
                  max={10}
                  value={sliders.creativity}
                  onChange={(e) => handleSliderChange('creativity', Number(e.target.value))}
                  className="w-full accent-sky-500"
                />
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Resemblance (ControlNet)</span>
                  <span className="font-mono text-indigo-400 font-bold">
                    {sliders.resemblance > 0 ? `+${sliders.resemblance}` : sliders.resemblance}
                  </span>
                </div>
                <input
                  type="range"
                  min={-10}
                  max={10}
                  value={sliders.resemblance}
                  onChange={(e) => handleSliderChange('resemblance', Number(e.target.value))}
                  className="w-full accent-indigo-500"
                />
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">Fractality</span>
                  <span className="font-mono text-amber-400 font-bold">
                    {sliders.fractality > 0 ? `+${sliders.fractality}` : sliders.fractality}
                  </span>
                </div>
                <input
                  type="range"
                  min={-10}
                  max={10}
                  value={sliders.fractality}
                  onChange={(e) => handleSliderChange('fractality', Number(e.target.value))}
                  className="w-full accent-amber-500"
                />
              </div>

              <div className="space-y-1">
                <div className="flex justify-between text-xs">
                  <span className="text-slate-300">HDR / Contrast</span>
                  <span className="font-mono text-emerald-400 font-bold">
                    {sliders.hdr > 0 ? `+${sliders.hdr}` : sliders.hdr}
                  </span>
                </div>
                <input
                  type="range"
                  min={-10}
                  max={10}
                  value={sliders.hdr}
                  onChange={(e) => handleSliderChange('hdr', Number(e.target.value))}
                  className="w-full accent-emerald-500"
                />
              </div>
            </div>

            {/* Prompt */}
            <div className="space-y-1.5">
              <label className="text-xs font-semibold text-slate-300">Prompt Guidance</label>
              <textarea
                rows={3}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Optional text prompt..."
                className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2 text-xs text-slate-200 placeholder-slate-500"
              />
            </div>
          </div>

          <div className="border-t border-slate-800 pt-4 flex gap-2">
            <button
              onClick={() => handlePresetSelect('vivid')}
              className="flex-1 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs"
            >
              Reset
            </button>
            <button
              onClick={() => setInspectorOpen(false)}
              className="flex-1 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold"
            >
              Done
            </button>
          </div>
        </aside>
      )}
    </div>
  );
}
