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
  QueueItem,
  mapCreativityToDenoise,
  mapResemblanceToControlNet,
} from './types';
import {
  Sparkles,
  Sliders,
  Layers,
  Wand2,
  ListPlus,
  Play,
  RotateCcw,
  CheckCircle2,
  Clock,
  Trash2,
  Info,
} from 'lucide-react';

export default function VariantA() {
  const [scale, setScale] = useState<ScaleFactor>('4x');
  const [preset, setPreset] = useState<PresetType>('vivid');
  const [category, setCategory] = useState<ContentCategory>('portraits');
  const [sliders, setSliders] = useState<SliderValues>(PRESET_RECIPES.vivid.sliders);
  const [prompt, setPrompt] = useState('high fidelity, skin pores, natural lighting, 8k uhd');
  const [queue, setQueue] = useState<QueueItem[]>([
    {
      id: 'q-1',
      name: 'portrait_studio_01.png',
      size: '1.2 MB',
      dimensions: '512×512',
      targetScale: '4x',
      preset: 'vivid',
      category: 'portraits',
      prompt: 'high fidelity, skin pores, natural lighting',
      status: 'completed',
      progress: 100,
      previewUrl:
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=50',
      resultUrl:
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=1600&q=90',
    },
    {
      id: 'q-2',
      name: 'cyberpunk_cityscape.jpg',
      size: '2.4 MB',
      dimensions: '768×512',
      targetScale: '4x',
      preset: 'wild',
      category: 'architecture',
      prompt: 'neon reflections, wet asphalt, sharp geometric lines',
      status: 'diffusing',
      progress: 65,
      stepMessage: 'Diffusing tile 9/16 (SDXL + ControlNet-Tile)',
      previewUrl:
        'https://images.unsplash.com/photo-1519501025264-65ba15a82390?auto=format&fit=crop&w=400&q=50',
    },
    {
      id: 'q-3',
      name: 'mountain_valley.png',
      size: '3.1 MB',
      dimensions: '1024×640',
      targetScale: '2x',
      preset: 'subtle',
      category: 'landscapes',
      prompt: 'rocky cliffs, pine trees, crisp atmospheric haze',
      status: 'queued',
      progress: 0,
      previewUrl:
        'https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=400&q=50',
    },
  ]);

  const handlePresetSelect = (p: PresetType) => {
    setPreset(p);
    setSliders(PRESET_RECIPES[p].sliders);
  };

  const handleSliderChange = (key: keyof SliderValues, value: number) => {
    setSliders((prev) => ({ ...prev, [key]: value }));
    setPreset('custom');
  };

  const handleAddToQueue = () => {
    const newItem: QueueItem = {
      id: `q-${Date.now()}`,
      name: `custom_upscale_${scale}.png`,
      size: '2.1 MB',
      dimensions: '512×512',
      targetScale: scale,
      preset,
      category,
      prompt,
      status: 'queued',
      progress: 0,
      previewUrl:
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=400&q=50',
    };
    setQueue((prev) => [newItem, ...prev]);
  };

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-sky-400" />
            Magnific Generative Upscaler
            <span className="text-xs font-mono font-medium px-2 py-0.5 rounded bg-sky-950/70 border border-sky-800/80 text-sky-300">
              Variant A: Studio Workspace
            </span>
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Tile-based diffusion upscaling with structure guidance, feather blending, and -10..+10 parameter precision.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Scale Factor:</span>
          {(['2x', '4x', '8x', '16x'] as ScaleFactor[]).map((s) => (
            <button
              key={s}
              onClick={() => setScale(s)}
              className={`px-3 py-1 rounded-md text-xs font-bold transition ${
                scale === s
                  ? 'bg-sky-500 text-slate-950 shadow-md shadow-sky-500/20'
                  : 'bg-slate-850 hover:bg-slate-800 text-slate-300 border border-slate-700/60'
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Main Two-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Control Stack (5 cols) */}
        <div className="lg:col-span-5 space-y-5">
          {/* Preset Buttons */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-sky-400" />
                Fidelity Preset
              </label>
              <span className="text-[11px] text-slate-400 font-mono capitalize">
                {preset} Mode
              </span>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {(['subtle', 'vivid', 'wild', 'custom'] as PresetType[]).map((p) => (
                <button
                  key={p}
                  onClick={() => handlePresetSelect(p)}
                  className={`py-1.5 px-2 rounded-lg text-xs font-medium capitalize text-center transition ${
                    preset === p
                      ? 'bg-sky-600 text-white font-bold shadow-sm'
                      : 'bg-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-750'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
            <p className="text-[11px] text-slate-400">
              {PRESET_RECIPES[preset].description}
            </p>
          </div>

          {/* Content Categories */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Wand2 className="w-3.5 h-3.5 text-indigo-400" />
              Content Category (v1 Core)
            </label>
            <div className="grid grid-cols-2 gap-2">
              {CATEGORIES.map((cat) => (
                <button
                  key={cat.id}
                  onClick={() => setCategory(cat.id)}
                  className={`p-2 rounded-lg text-left border text-xs transition ${
                    category === cat.id
                      ? 'bg-indigo-950/40 border-indigo-500/80 text-indigo-200 font-medium'
                      : 'bg-slate-850/60 border-slate-800 text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                  }`}
                >
                  <div className="font-semibold text-slate-200">{cat.label}</div>
                  <div className="text-[10px] text-slate-400 truncate">{cat.description}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Slider Bank */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-4">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Sliders className="w-3.5 h-3.5 text-sky-400" />
                Fine-Grained Parameter Sliders (-10 to +10)
              </label>
              <button
                onClick={() => handlePresetSelect('vivid')}
                className="text-[10px] text-slate-400 hover:text-slate-200 flex items-center gap-1"
                title="Reset to default"
              >
                <RotateCcw className="w-3 h-3" /> Reset
              </button>
            </div>

            {/* Creativity Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-300 font-medium">Creativity (Denoise)</span>
                <span className="font-mono text-sky-400 font-bold">
                  {sliders.creativity > 0 ? `+${sliders.creativity}` : sliders.creativity}
                  <span className="text-[10px] text-slate-400 font-normal ml-1.5">
                    (denoise: {mapCreativityToDenoise(sliders.creativity)})
                  </span>
                </span>
              </div>
              <input
                type="range"
                min={-10}
                max={10}
                step={1}
                value={sliders.creativity}
                onChange={(e) => handleSliderChange('creativity', Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-sky-500"
              />
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>Faithful (-10)</span>
                <span>Balanced (0)</span>
                <span>Hallucinated (+10)</span>
              </div>
            </div>

            {/* Resemblance Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-300 font-medium">Resemblance (ControlNet)</span>
                <span className="font-mono text-indigo-400 font-bold">
                  {sliders.resemblance > 0 ? `+${sliders.resemblance}` : sliders.resemblance}
                  <span className="text-[10px] text-slate-400 font-normal ml-1.5">
                    (weight: {mapResemblanceToControlNet(sliders.resemblance)})
                  </span>
                </span>
              </div>
              <input
                type="range"
                min={-10}
                max={10}
                step={1}
                value={sliders.resemblance}
                onChange={(e) => handleSliderChange('resemblance', Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500"
              />
              <div className="flex justify-between text-[10px] text-slate-400">
                <span>Loose (-10)</span>
                <span>Guided (0)</span>
                <span>Strict (+10)</span>
              </div>
            </div>

            {/* Fractality Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-300 font-medium">Fractality (Tile Micro-Scale)</span>
                <span className="font-mono text-amber-400 font-bold">
                  {sliders.fractality > 0 ? `+${sliders.fractality}` : sliders.fractality}
                </span>
              </div>
              <input
                type="range"
                min={-10}
                max={10}
                step={1}
                value={sliders.fractality}
                onChange={(e) => handleSliderChange('fractality', Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-500"
              />
            </div>

            {/* HDR Slider */}
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs">
                <span className="text-slate-300 font-medium">HDR & Micro-Contrast</span>
                <span className="font-mono text-emerald-400 font-bold">
                  {sliders.hdr > 0 ? `+${sliders.hdr}` : sliders.hdr}
                </span>
              </div>
              <input
                type="range"
                min={-10}
                max={10}
                step={1}
                value={sliders.hdr}
                onChange={(e) => handleSliderChange('hdr', Number(e.target.value))}
                className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-emerald-500"
              />
            </div>
          </div>

          {/* Prompt Field */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-2">
            <label className="text-xs font-semibold text-slate-300">
              Positive Enhancement Prompt (Optional)
            </label>
            <textarea
              rows={2}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. ultra-detailed skin textures, 8k photograph, cinematic lighting..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-2.5 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Action CTAs */}
          <div className="flex items-center gap-3">
            <button
              onClick={handleAddToQueue}
              className="flex-1 py-2.5 px-4 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              Upscale Now ({scale})
            </button>
            <button
              onClick={handleAddToQueue}
              className="py-2.5 px-4 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold transition flex items-center gap-1.5"
            >
              <ListPlus className="w-3.5 h-3.5" />
              Queue
            </button>
          </div>
        </div>

        {/* Right Column: Interactive Compare Canvas & Bulk Queue (7 cols) */}
        <div className="lg:col-span-7 space-y-6">
          {/* Compare Viewport */}
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs text-slate-400">
              <span className="flex items-center gap-1.5 font-medium text-slate-300">
                <Info className="w-3.5 h-3.5 text-sky-400" />
                Interactive Before / After Split Slider
              </span>
              <span className="font-mono text-[11px] text-slate-500">
                Drag center divider horizontally
              </span>
            </div>

            <CompareSlider
              beforeUrl="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=40"
              afterUrl="https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=2400&q=95"
              beforeLabel="Original 1x (512×512)"
              afterLabel={`Upscaled ${scale} (2048×2048 • SDXL-Tile)`}
              aspectRatio="aspect-[16/10]"
            />

            {/* Canvas Info Strip */}
            <div className="flex items-center justify-between px-3 py-2 bg-slate-900/60 border border-slate-800/80 rounded-lg text-[11px] text-slate-400 font-mono">
              <div>Output: 2048×2048 px (16 overlapping tiles)</div>
              <div>Engine: SDXL + ControlNet-Tile • Feather Blend 64px</div>
            </div>
          </div>

          {/* Bulk Queue Tray */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-sky-400" />
                Upscale Queue ({queue.length} items)
              </h3>
              <button
                onClick={() => setQueue([])}
                className="text-[11px] text-slate-400 hover:text-rose-400 transition"
              >
                Clear all
              </button>
            </div>

            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {queue.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 p-2.5 bg-slate-950/60 border border-slate-800 rounded-lg text-xs"
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={item.previewUrl}
                    alt={item.name}
                    className="w-10 h-10 rounded object-cover border border-slate-700 flex-shrink-0"
                  />

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-200 truncate">{item.name}</span>
                      <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-slate-800 text-sky-300">
                        {item.targetScale}
                      </span>
                    </div>

                    <div className="flex items-center gap-2 text-[10px] text-slate-400 mt-0.5">
                      <span>{item.dimensions}</span>
                      <span>•</span>
                      <span className="capitalize">{item.preset}</span>
                      <span>•</span>
                      <span className="capitalize">{item.category}</span>
                    </div>

                    {/* Progress Bar */}
                    {item.status === 'diffusing' && (
                      <div className="mt-1.5 space-y-1">
                        <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-sky-500 rounded-full transition-all duration-300"
                            style={{ width: `${item.progress}%` }}
                          />
                        </div>
                        <div className="text-[9px] text-sky-400 font-mono">
                          {item.stepMessage}
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Status Indicator */}
                  <div className="flex items-center gap-2">
                    {item.status === 'completed' && (
                      <span className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Done
                      </span>
                    )}
                    {item.status === 'queued' && (
                      <span className="flex items-center gap-1 text-[11px] text-slate-400">
                        <Clock className="w-3.5 h-3.5" />
                        Pending
                      </span>
                    )}
                    {item.status === 'diffusing' && (
                      <span className="text-[11px] text-sky-400 font-mono font-bold">
                        {item.progress}%
                      </span>
                    )}
                    <button
                      onClick={() => setQueue((prev) => prev.filter((q) => q.id !== item.id))}
                      className="p-1 text-slate-400 hover:text-rose-400"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
