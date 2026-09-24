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
} from './types';
import {
  Sparkles,
  Layers,
  Play,
  CheckCircle2,
  Clock,
  Maximize2,
  X,
  Sliders,
  Filter,
  CheckCheck,
} from 'lucide-react';

export default function VariantC() {
  const [scale, setScale] = useState<ScaleFactor>('4x');
  const [preset, setPreset] = useState<PresetType>('vivid');
  const [category, setCategory] = useState<ContentCategory>('universal');
  const [modalItem, setModalItem] = useState<QueueItem | null>(null);

  const [items, setItems] = useState<QueueItem[]>([
    {
      id: 'c-1',
      name: 'portrait_girl_bokeh.jpg',
      size: '1.4 MB',
      dimensions: '512×512',
      targetScale: '4x',
      preset: 'subtle',
      category: 'portraits',
      prompt: 'sharp focus on eyes, natural pores',
      status: 'completed',
      progress: 100,
      previewUrl:
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=40',
      resultUrl:
        'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=2400&q=95',
    },
    {
      id: 'c-2',
      name: 'futuristic_supercar.png',
      size: '2.8 MB',
      dimensions: '640×400',
      targetScale: '4x',
      preset: 'wild',
      category: 'product',
      prompt: 'glossy carbon fiber, studio softbox reflections',
      status: 'diffusing',
      progress: 45,
      stepMessage: 'Tile 7/16 (SDXL)',
      previewUrl:
        'https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=600&q=40',
    },
    {
      id: 'c-3',
      name: 'misty_norwegian_fjord.jpg',
      size: '3.2 MB',
      dimensions: '800×500',
      targetScale: '4x',
      preset: 'vivid',
      category: 'landscapes',
      prompt: 'water ripples, evergreen pines, overcast clouds',
      status: 'queued',
      progress: 0,
      previewUrl:
        'https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=600&q=40',
    },
    {
      id: 'c-4',
      name: 'mecha_pilot_character.png',
      size: '1.9 MB',
      dimensions: '512×512',
      targetScale: '4x',
      preset: 'vivid',
      category: 'anime',
      prompt: 'crisp cel shading, vibrant neon armor accents',
      status: 'queued',
      progress: 0,
      previewUrl:
        'https://images.unsplash.com/photo-1578632767115-351597cf2477?auto=format&fit=crop&w=600&q=40',
    },
  ]);

  const applyGlobalSettingsToAll = () => {
    setItems((prev) =>
      prev.map((it) => ({
        ...it,
        targetScale: scale,
        preset,
        category,
      }))
    );
  };

  return (
    <div className="space-y-6">
      {/* Top Batch Control Strip */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl p-4 shadow-xl backdrop-blur-md space-y-4">
        <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4 border-b border-slate-800 pb-3">
          <div>
            <h2 className="text-base font-bold text-white flex items-center gap-2">
              <Layers className="w-5 h-5 text-sky-400" />
              Batch Upscale Catalog
              <span className="text-xs font-mono font-medium px-2 py-0.5 rounded bg-emerald-950/70 border border-emerald-800 text-emerald-300">
                Variant C: Batch-First Grid
              </span>
            </h2>
            <p className="text-xs text-slate-400">
              Bulk queue management: configure global parameters, apply across multiple assets, and inspect results.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button
              onClick={applyGlobalSettingsToAll}
              className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition"
            >
              <CheckCheck className="w-3.5 h-3.5 text-sky-400" />
              Apply to All ({items.length})
            </button>
            <button className="px-4 py-2 bg-gradient-to-r from-sky-500 to-indigo-600 hover:from-sky-400 hover:to-indigo-500 text-white rounded-lg text-xs font-bold shadow-lg shadow-sky-500/20 flex items-center gap-2 transition">
              <Play className="w-3.5 h-3.5 fill-current" />
              Start Bulk Upscale ({items.length} items)
            </button>
          </div>
        </div>

        {/* Global Parameter Bar */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {/* Scale */}
          <div className="flex items-center gap-2 bg-slate-950/60 p-2 rounded-xl border border-slate-800/80">
            <span className="text-xs text-slate-400 font-medium pl-1">Scale:</span>
            <div className="flex gap-1 flex-1">
              {(['2x', '4x', '8x'] as ScaleFactor[]).map((s) => (
                <button
                  key={s}
                  onClick={() => setScale(s)}
                  className={`flex-1 py-1 rounded-lg text-xs font-bold transition ${
                    scale === s
                      ? 'bg-sky-500 text-slate-950'
                      : 'bg-slate-800/70 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Preset */}
          <div className="flex items-center gap-2 bg-slate-950/60 p-2 rounded-xl border border-slate-800/80">
            <span className="text-xs text-slate-400 font-medium pl-1">Preset:</span>
            <div className="flex gap-1 flex-1">
              {(['subtle', 'vivid', 'wild'] as PresetType[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setPreset(p)}
                  className={`flex-1 py-1 rounded-lg text-xs font-semibold capitalize transition ${
                    preset === p
                      ? 'bg-indigo-600 text-white'
                      : 'bg-slate-800/70 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>

          {/* Category */}
          <div className="flex items-center gap-2 bg-slate-950/60 p-2 rounded-xl border border-slate-800/80">
            <span className="text-xs text-slate-400 font-medium pl-1">Category:</span>
            <select
              value={category}
              onChange={(e) => setCategory(e.target.value as ContentCategory)}
              className="flex-1 bg-slate-900 border border-slate-700/80 rounded-lg p-1 text-xs text-slate-200"
            >
              {CATEGORIES.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Grid of Batch Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {items.map((item) => (
          <div
            key={item.id}
            className="bg-slate-900/70 border border-slate-800 rounded-xl overflow-hidden shadow-lg flex flex-col group hover:border-slate-700 transition"
          >
            {/* Card Thumbnail / Preview */}
            <div className="relative aspect-[4/3] bg-slate-950 overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={item.resultUrl || item.previewUrl}
                alt={item.name}
                className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
              />

              {/* Status Badge */}
              <div className="absolute top-2 left-2 z-10">
                {item.status === 'completed' && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-emerald-950/90 border border-emerald-500/50 rounded-full text-emerald-300 text-[10px] font-semibold backdrop-blur-md">
                    <CheckCircle2 className="w-3 h-3 text-emerald-400" /> Completed
                  </span>
                )}
                {item.status === 'diffusing' && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-sky-950/90 border border-sky-500/50 rounded-full text-sky-300 text-[10px] font-semibold backdrop-blur-md animate-pulse">
                    <Play className="w-3 h-3 text-sky-400 fill-current" /> {item.progress}%
                  </span>
                )}
                {item.status === 'queued' && (
                  <span className="flex items-center gap-1 px-2 py-0.5 bg-slate-900/90 border border-slate-700 rounded-full text-slate-400 text-[10px] font-semibold backdrop-blur-md">
                    <Clock className="w-3 h-3" /> Queued
                  </span>
                )}
              </div>

              {/* Target Scale Badge */}
              <div className="absolute top-2 right-2 z-10 px-2 py-0.5 bg-slate-900/90 border border-slate-700 rounded-full text-white text-[10px] font-mono font-bold backdrop-blur-md">
                {item.targetScale}
              </div>

              {/* Quick Compare Button on Hover */}
              <button
                onClick={() => setModalItem(item)}
                className="absolute inset-0 m-auto w-10 h-10 rounded-full bg-slate-900/90 border border-white/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition shadow-2xl backdrop-blur-md hover:scale-110"
                title="Inspect in Before/After Compare View"
              >
                <Maximize2 className="w-4 h-4 text-sky-400" />
              </button>
            </div>

            {/* Card Body */}
            <div className="p-3 space-y-2.5 flex-1 flex flex-col justify-between">
              <div>
                <div className="font-semibold text-xs text-slate-200 truncate">{item.name}</div>
                <div className="text-[10px] text-slate-400 font-mono flex items-center gap-2 mt-0.5">
                  <span>{item.dimensions}</span>
                  <span>→</span>
                  <span className="text-sky-400 font-bold">2048×2048</span>
                </div>
              </div>

              {/* Progress bar if active */}
              {item.status === 'diffusing' && (
                <div className="space-y-1">
                  <div className="w-full h-1 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-sky-500 rounded-full"
                      style={{ width: `${item.progress}%` }}
                    />
                  </div>
                  <div className="text-[9px] text-sky-400 font-mono truncate">{item.stepMessage}</div>
                </div>
              )}

              {/* Preset & Category tags */}
              <div className="flex items-center justify-between text-[10px] pt-1 border-t border-slate-800/80">
                <span className="capitalize px-1.5 py-0.5 bg-slate-800 rounded text-slate-300 font-medium">
                  {item.preset}
                </span>
                <span className="capitalize text-slate-400">{item.category}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Compare Modal */}
      {modalItem && (
        <div className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-md flex items-center justify-center p-4 sm:p-6 animate-in fade-in duration-150">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-4xl p-5 space-y-4 shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div>
                <h3 className="font-bold text-sm text-white flex items-center gap-2">
                  <Sparkles className="w-4 h-4 text-sky-400" />
                  Before / After Compare: {modalItem.name}
                </h3>
                <p className="text-[11px] text-slate-400">
                  Target: {modalItem.targetScale} • Preset: {modalItem.preset} • Category:{' '}
                  {modalItem.category}
                </p>
              </div>
              <button
                onClick={() => setModalItem(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <CompareSlider
              beforeUrl={modalItem.previewUrl}
              afterUrl={modalItem.resultUrl || modalItem.previewUrl}
              beforeLabel={`Original 1x (${modalItem.dimensions})`}
              afterLabel={`Upscaled ${modalItem.targetScale} (2048×2048 • SDXL-Tile)`}
              aspectRatio="aspect-[16/10]"
            />

            <div className="flex items-center justify-between pt-2">
              <span className="text-xs text-slate-400 font-mono">
                Tile engine: 16 tiles • Denoise: 0.35 • ControlNet: 0.85
              </span>
              <button
                onClick={() => setModalItem(null)}
                className="px-4 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold transition"
              >
                Close View
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
