'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useStore } from '../store/useStore';
import {
  startTask,
  getTaskStatus,
  fetchMediaCatalog,
  MediaAsset,
  UpscaleParams,
  TaskResponse,
} from '../utils/api';
import {
  Sparkles,
  Loader2,
  Play,
  CheckCircle2,
  AlertCircle,
  Wand2,
  ArrowLeftRight,
} from 'lucide-react';
import BeforeAfterModal from './BeforeAfterModal';

/* Presets from features.md §5 (Upscaler presets). */
interface Preset {
  name: string;
  denoise: number;
  controlnet_weight: number;
  hdr: number;
  fractality: number;
}

const PRESETS: Preset[] = [
  { name: 'Portraits', denoise: 0.30, controlnet_weight: 0.85, hdr: 0.25, fractality: 0.15 },
  { name: 'Anime', denoise: 0.45, controlnet_weight: 0.75, hdr: 0.10, fractality: 0.20 },
  { name: 'Landscapes', denoise: 0.35, controlnet_weight: 0.80, hdr: 0.30, fractality: 0.25 },
  { name: 'Product Photography', denoise: 0.25, controlnet_weight: 0.90, hdr: 0.35, fractality: 0.10 },
  { name: '3D Renderings', denoise: 0.40, controlnet_weight: 0.70, hdr: 0.20, fractality: 0.30 },
];

interface SliderRow {
  key: keyof UpscaleParams;
  label: string;
  brand: string;
  hint: string;
  min: number;
  max: number;
  step: number;
}

const SLIDERS: SliderRow[] = [
  { key: 'denoise', label: 'Denoising Strength', brand: 'Creativity', hint: 'Amount of raw generative texture hallucinated', min: 0, max: 1, step: 0.01 },
  { key: 'controlnet_weight', label: 'ControlNet Weight', brand: 'Resemblance', hint: 'Enforces adherence to the low-res spatial structure', min: 0, max: 1, step: 0.01 },
  { key: 'hdr', label: 'HDR', brand: 'HDR', hint: 'UnsharpMask + Contrast post-pass (zero GPU cost)', min: 0, max: 1, step: 0.01 },
  { key: 'fractality', label: 'Fractality', brand: 'Fractality', hint: 'Pre-tile noise injection + guidance bump 7→12', min: 0, max: 1, step: 0.01 },
];

interface RunningTask {
  id: string;
  state: string;
  percent?: number;
  statusText?: string;
}

export default function UpscalerPanel() {
  const { upscaleTarget, setUpscaleTarget, activeTab } = useStore();

  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [loadingAssets, setLoadingAssets] = useState(false);
  const [selectedPath, setSelectedPath] = useState<string | null>(upscaleTarget);

  const [params, setParams] = useState<UpscaleParams>({
    denoise: 0.35,
    controlnet_weight: 0.8,
    hdr: 0.0,
    fractality: 0.0,
    prompt: '',
  });
  const [activePreset, setActivePreset] = useState<string | null>(null);

  const [runningTask, setRunningTask] = useState<RunningTask | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<{ beforeUrl: string; afterUrl: string; title: string } | null>(null);
  const [showCompare, setShowCompare] = useState(false);

  // Sync selection when FileManager/catalog sets a new upscale target.
  useEffect(() => {
    if (upscaleTarget) {
      setSelectedPath(upscaleTarget);
    }
  }, [upscaleTarget]);

  const loadAssets = useCallback(async () => {
    setLoadingAssets(true);
    try {
      const catalog = await fetchMediaCatalog('', 50);
      setAssets(catalog.filter((a) => a.content_type.toLowerCase().startsWith('image/')));
    } catch {
      /* backend unreachable — keep whatever we have */
    } finally {
      setLoadingAssets(false);
    }
  }, []);

  useEffect(() => {
    loadAssets();
  }, [loadAssets, activeTab]);

  const updateParam = (key: keyof UpscaleParams, value: number | string) => {
    setParams((prev) => ({ ...prev, [key]: value }));
    setActivePreset(null);
  };

  const applyPreset = (preset: Preset) => {
    setParams({
      ...params,
      denoise: preset.denoise,
      controlnet_weight: preset.controlnet_weight,
      hdr: preset.hdr,
      fractality: preset.fractality,
    });
    setActivePreset(preset.name);
  };

  const handleRun = async () => {
    if (!selectedPath) {
      setTaskError('Select an image to upscale first.');
      return;
    }
    setTaskError(null);
    setLastResult(null);
    try {
      const res: TaskResponse = await startTask(selectedPath, 'upscale', params);
      setRunningTask({ id: res.task_id, state: res.status, percent: 0 });
    } catch (err: any) {
      setTaskError(err.message || 'Failed to dispatch upscale task');
    }
  };

  // Poll the running task to completion.
  useEffect(() => {
    if (!runningTask) return;
    const interval = setInterval(async () => {
      try {
        const status = await getTaskStatus(runningTask.id);
        const next: RunningTask = { ...runningTask, state: status.state };
        if (status.state === 'PROGRESS' && status.info) {
          next.percent = status.info.percent;
          next.statusText = status.info.status;
        } else if (status.state === 'SUCCESS') {
          next.percent = 100;
          next.statusText = 'Completed';
          const info = status.info || {};
          if (info.processed_url && info.original_object) {
            // Find the original asset URL from the loaded catalog so the
            // before/after modal can pair them (#58).
            const originalAsset = assets.find(
              (a) => a.file_path === info.original_object
            );
            setLastResult({
              beforeUrl: originalAsset?.url || '',
              afterUrl: info.processed_url,
              title: info.processed_name || selectedPath || 'Upscale Comparison',
            });
          }
          setRunningTask(null);
          clearInterval(interval);
          loadAssets();
          return;
        } else if (status.state === 'FAILURE') {
          next.statusText = `Error: ${status.info}`;
          setTaskError(typeof status.info === 'string' ? status.info : 'Upscale failed');
          setRunningTask(null);
          clearInterval(interval);
          return;
        }
        setRunningTask(next);
      } catch {
        /* transient poll failure — keep polling */
      }
    }, 1500);
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runningTask?.id]);

  const percent = runningTask?.percent ?? 0;

  return (
    <div className="space-y-8 animate-fadeIn max-w-6xl">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h2 className="text-xl font-bold text-white flex items-center gap-2 mb-2">
          <Wand2 className="w-5 h-5 text-sky-400" /> Magnific-Style Generative Upscaler
        </h2>
        <p className="text-sm text-slate-400 max-w-3xl">
          Tile-based upscaling with ControlNet Tile + SDXL/Flux. Additive HDR and Fractality
          controls (map #57) and optional text-prompt guidance (map #59) — forwarded to the
          Colab diffusion worker, or run through the local CPU fallback pipeline when no
          worker is connected.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Left: target + controls */}
        <div className="space-y-6">
          {/* Target image */}
          <section className="bg-slate-900 border border-slate-800 rounded-lg p-5">
            <h3 className="text-sm font-bold text-slate-200 mb-4 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" /> Target Image
            </h3>
            <select
              value={selectedPath ?? ''}
              onChange={(e) => setSelectedPath(e.target.value || null)}
              className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500"
            >
              <option value="">Select an image…</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.file_path}>
                  {asset.title}
                </option>
              ))}
            </select>
            {loadingAssets && (
              <p className="text-[10px] text-slate-500 mt-2 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" /> Loading catalog images…
              </p>
            )}
            {selectedPath && !loadingAssets && (
              <p className="text-[10px] text-slate-500 mt-2 font-mono break-all">{selectedPath}</p>
            )}
          </section>

          {/* Sliders */}
          <section className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-5">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" /> Fidelity Controls
            </h3>
            {SLIDERS.map((slider) => {
              const value = (params[slider.key] as number) ?? 0;
              return (
                <div key={slider.key}>
                  <div className="flex items-center justify-between mb-1.5">
                    <label className="text-xs font-semibold text-slate-300">
                      {slider.label}
                      {slider.brand && slider.brand !== slider.label && (
                        <span className="text-slate-500 font-normal"> — {slider.brand}</span>
                      )}
                    </label>
                    <span className="text-xs font-mono text-sky-400">{value.toFixed(2)}</span>
                  </div>
                  <input
                    type="range"
                    min={slider.min}
                    max={slider.max}
                    step={slider.step}
                    value={value}
                    onChange={(e) => updateParam(slider.key, parseFloat(e.target.value))}
                    className="w-full accent-sky-500"
                  />
                  <p className="text-[10px] text-slate-500 mt-1">{slider.hint}</p>
                </div>
              );
            })}
          </section>

          {/* Prompt + presets */}
          <section className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-5">
            <h3 className="text-sm font-bold text-slate-200 flex items-center gap-2">
              <Sparkles className="w-4 h-4 text-sky-400" /> Prompt Guidance
            </h3>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                Optional img2img prompt
              </label>
              <input
                type="text"
                placeholder="e.g. ultra-detailed skin pores, sharp foliage"
                value={params.prompt || ''}
                onChange={(e) => updateParam('prompt', e.target.value)}
                className="w-full bg-slate-950 border border-slate-700 rounded-md px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500"
              />
              <p className="text-[10px] text-slate-500 mt-1">
                Used as the positive prompt for each tile pass. Empty = current behavior (map #59).
              </p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-2">Presets</label>
              <div className="flex flex-wrap gap-1.5">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.name}
                    onClick={() => applyPreset(preset)}
                    className={`text-[10px] font-semibold px-2.5 py-1 rounded border transition ${
                      activePreset === preset.name
                        ? 'bg-sky-950 text-sky-300 border-sky-800'
                        : 'bg-slate-950 text-slate-400 border-slate-700 hover:border-slate-500 hover:text-slate-200'
                    }`}
                  >
                    {preset.name}
                  </button>
                ))}
              </div>
            </div>
          </section>

          {/* Run */}
          <section className="bg-slate-900 border border-slate-800 rounded-lg p-5">
            <button
              onClick={handleRun}
              disabled={!!runningTask}
              className="w-full flex items-center justify-center gap-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm px-6 py-3 rounded-md transition active:scale-[98%]"
            >
              {runningTask ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
              {runningTask ? 'Upscaling…' : 'Run Upscale'}
            </button>

            {runningTask && (
              <div className="mt-4">
                <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                  <div className="bg-sky-500 h-full transition-all duration-300" style={{ width: `${Math.max(percent, 5)}%` }} />
                </div>
                <p className="text-xs text-slate-400 mt-2 flex items-center gap-1.5">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                  {runningTask.statusText || `Processing… ${Math.round(percent)}%`}
                </p>
              </div>
            )}

            {taskError && (
              <p className="text-xs text-rose-400 mt-3 flex items-center gap-1.5 bg-rose-950/30 border border-rose-900/50 rounded-md px-3 py-2">
                <AlertCircle className="w-3.5 h-3.5" /> {taskError}
              </p>
            )}

            {lastResult && (
              <div className="mt-4 bg-emerald-950/20 border border-emerald-900/60 rounded-md p-3 flex items-center justify-between gap-3">
                <p className="text-xs text-emerald-300 flex items-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> Upscale complete — result saved to catalog.
                </p>
                <button
                  onClick={() => setShowCompare(true)}
                  className="flex items-center gap-1.5 text-xs font-semibold bg-emerald-800/60 hover:bg-emerald-700/60 text-emerald-100 border border-emerald-700 px-3 py-1.5 rounded transition"
                >
                  <ArrowLeftRight className="w-3.5 h-3.5" /> Compare
                </button>
              </div>
            )}
          </section>
        </div>

        {/* Right: guide panel */}
        <div className="space-y-6">
          <section className="bg-slate-900 border border-slate-800 rounded-lg p-5">
            <h3 className="text-sm font-bold text-slate-200 mb-3">How controls map to the pipeline</h3>
            <ul className="space-y-3 text-xs text-slate-400">
              <li>
                <strong className="text-slate-200">Denoising Strength — Creativity</strong>
                <p className="text-slate-500 mt-0.5">img2img denoise strength per tile pass.</p>
              </li>
              <li>
                <strong className="text-slate-200">ControlNet Weight — Resemblance</strong>
                <p className="text-slate-500 mt-0.5">Tile ControlNet conditioning weight.</p>
              </li>
              <li>
                <strong className="text-slate-200">HDR</strong>
                <p className="text-slate-500 mt-0.5">PIL UnsharpMask + Contrast post-pass — zero GPU cost (map #61).</p>
              </li>
              <li>
                <strong className="text-slate-200">Fractality</strong>
                <p className="text-slate-500 mt-0.5">Pre-tile Gaussian noise injection + guidance_scale bump 7→12 (map #61).</p>
              </li>
              <li>
                <strong className="text-slate-200">Prompt</strong>
                <p className="text-slate-500 mt-0.5">img2img positive prompt per tile; empty preserves current behavior (map #59).</p>
              </li>
            </ul>
          </section>
        </div>
      </div>

      {showCompare && lastResult && lastResult.beforeUrl && (
        <BeforeAfterModal
          beforeUrl={lastResult.beforeUrl}
          afterUrl={lastResult.afterUrl}
          title={lastResult.title}
          onClose={() => setShowCompare(false)}
        />
      )}

    </div>
  );
}
