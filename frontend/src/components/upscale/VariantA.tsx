'use client';

import React, { useState, useEffect, useCallback } from 'react';
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
  fetchFiles,
  startUpscale,
  getUpscaleStatus,
  fetchUpscalePresets,
  fetchUpscaleCategories,
  StorageItem,
  UpscalePresetDefinition,
  UpscaleCategoryDefinition,
} from '../../utils/api';
import {
  resolveUpscaleParams,
  scaleFactorToInt,
  MAX_BULK_QUEUE,
  isUpscalableImage,
} from '../../utils/upscale';
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
  RefreshCw,
  Loader2,
  AlertCircle,
} from 'lucide-react';

function formatBytes(bytes?: number): string {
  if (!bytes) return '—';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(2))} ${sizes[i]}`;
}

function backendStatusToQueueState(status: string): QueueItem['status'] {
  switch (status) {
    case 'COMPLETED':
      return 'completed';
    case 'FAILED':
      return 'error';
    case 'PROCESSING':
      return 'diffusing';
    default:
      return 'queued';
  }
}

interface CompareContext {
  beforeUrl: string;
  afterUrl: string;
  beforeLabel: string;
  afterLabel: string;
}

export default function VariantA() {
  const [scale, setScale] = useState<ScaleFactor>('4x');
  const [preset, setPreset] = useState<PresetType>('vivid');
  const [category, setCategory] = useState<ContentCategory>('portraits');
  const [sliders, setSliders] = useState<SliderValues>(PRESET_RECIPES.vivid.sliders);
  const [prompt, setPrompt] = useState('high fidelity, skin pores, natural lighting, 8k uhd');

  // Live engine registries (#96) — fetched from /api/upscale/presets|categories
  const [livePresets, setLivePresets] = useState<Record<string, UpscalePresetDefinition> | null>(null);
  const [liveCategories, setLiveCategories] = useState<Record<string, UpscaleCategoryDefinition> | null>(null);

  // Source images from MinIO (#96)
  const [sources, setSources] = useState<StorageItem[]>([]);
  const [selectedPath, setSelectedPath] = useState<string>('');
  const [loadingSources, setLoadingSources] = useState(true);

  // Real upscale queue (starts empty — no mock data ships) (#96)
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [compare, setCompare] = useState<CompareContext | null>(null);

  const selectedSource = sources.find((s) => s.path === selectedPath) ?? null;

  const loadSources = useCallback(async () => {
    setLoadingSources(true);
    try {
      const data = await fetchFiles('');
      const images = (data.files || []).filter((f) => isUpscalableImage(f.name));
      setSources(images);
    } catch {
      /* backend unreachable — leave list empty with hint below */
    } finally {
      setLoadingSources(false);
    }
  }, []);

  useEffect(() => {
    loadSources();
    fetchUpscalePresets().then(setLivePresets).catch(() => setLivePresets(null));
    fetchUpscaleCategories().then(setLiveCategories).catch(() => setLiveCategories(null));
  }, [loadSources]);

  const categoryEntries: { id: ContentCategory; label: string; description: string }[] =
    liveCategories && Object.keys(liveCategories).length > 0
      ? Object.entries(liveCategories).map(([id, def]) => ({
          id: id as ContentCategory,
          label: def.label,
          description: def.description,
        }))
      : CATEGORIES;

  const presetDescription =
    livePresets?.[preset]?.description ?? PRESET_RECIPES[preset].description;

  const handlePresetSelect = (p: PresetType) => {
    setPreset(p);
    setSliders(PRESET_RECIPES[p].sliders);
  };

  const handleSliderChange = (key: keyof SliderValues, value: number) => {
    setSliders((prev) => ({ ...prev, [key]: value }));
    setPreset('custom');
  };

  const buildPayload = (source: StorageItem) => {
    const params = resolveUpscaleParams(preset, {
      scale: scaleFactorToInt(scale),
      creativity: sliders.creativity,
      resemblance: sliders.resemblance,
      fractality: sliders.fractality,
      hdr: sliders.hdr,
      category,
      prompt: prompt.trim() || undefined,
    });
    return {
      image_path: source.path,
      scale: params.scale,
      preset: params.preset,
      creativity: params.creativity,
      resemblance: params.resemblance,
      fractality: params.fractality,
      hdr: params.hdr,
      category: params.category,
      prompt: params.prompt,
    };
  };

  const makeQueuedItem = (source: StorageItem): QueueItem => ({
    id: `local-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    name: source.name,
    size: formatBytes(source.size),
    dimensions: '—',
    targetScale: scale,
    preset,
    category,
    prompt,
    status: 'queued',
    progress: 0,
    previewUrl: source.url || '',
    sourcePath: source.path,
  });

  const dispatchSource = async (source: StorageItem): Promise<QueueItem> => {
    const res = await startUpscale(buildPayload(source));
    return {
      ...makeQueuedItem(source),
      id: res.task_id,
      taskId: res.task_id,
      status: backendStatusToQueueState(res.status),
      progress: 0,
    };
  };

  const handleUpscaleNow = async () => {
    if (!selectedSource) {
      setError('Select a source image from your library first.');
      return;
    }
    if (queue.length >= MAX_BULK_QUEUE) {
      setError(`Bulk queue is capped at ${MAX_BULK_QUEUE} items — clear some first.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const item = await dispatchSource(selectedSource);
      setQueue((prev) => [item, ...prev]);
    } catch (err: any) {
      setError(err.message || 'Upscale dispatch failed');
    } finally {
      setBusy(false);
    }
  };

  const handleAddToQueue = () => {
    if (!selectedSource) {
      setError('Select a source image from your library first.');
      return;
    }
    if (queue.length >= MAX_BULK_QUEUE) {
      setError(`Bulk queue is capped at ${MAX_BULK_QUEUE} items — clear some first.`);
      return;
    }
    setError(null);
    setQueue((prev) => [makeQueuedItem(selectedSource), ...prev]);
  };

  const handleStartBulk = async () => {
    const pending = queue.filter((q) => !q.taskId && q.sourcePath);
    if (pending.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      for (const item of pending) {
        const source = sources.find((s) => s.path === item.sourcePath);
        if (!source) continue;
        // Snapshot this item's own settings at dispatch time
        const res = await startUpscale({
          image_path: source.path,
          scale: scaleFactorToInt(item.targetScale),
          preset: item.preset,
          category: item.category,
          prompt: item.prompt.trim() || undefined,
        });
        setQueue((prev) =>
          prev.map((q) =>
            q.id === item.id
              ? {
                  ...q,
                  id: res.task_id,
                  taskId: res.task_id,
                  status: backendStatusToQueueState(res.status),
                  progress: 0,
                }
              : q
          )
        );
      }
    } catch (err: any) {
      setError(err.message || 'Bulk upscale dispatch failed');
    } finally {
      setBusy(false);
    }
  };

  // Poll dispatched jobs until terminal state (#96)
  useEffect(() => {
    const active = queue.filter(
      (q) => q.taskId && (q.status === 'queued' || q.status === 'diffusing')
    );
    if (active.length === 0) return;

    const interval = setInterval(async () => {
      for (const item of active) {
        if (!item.taskId) continue;
        try {
          const status = await getUpscaleStatus(item.taskId);
          const nextStatus = backendStatusToQueueState(status.status);
          setQueue((prev) =>
            prev.map((q) => {
              if (q.taskId !== item.taskId) return q;
              const updated: QueueItem = {
                ...q,
                status: nextStatus,
                progress: status.progress ?? q.progress,
                resultUrl: status.result_url ?? q.resultUrl,
                stepMessage:
                  nextStatus === 'diffusing'
                    ? status.logs || 'Diffusing tiles (SDXL + ControlNet-Tile)'
                    : undefined,
              };
              if (nextStatus === 'completed' && status.result_url) {
                setCompare({
                  beforeUrl: q.previewUrl,
                  afterUrl: status.result_url,
                  beforeLabel: `Original 1x — ${q.name}`,
                  afterLabel: `Upscaled ${q.targetScale} • SDXL-Tile (${q.preset})`,
                });
              }
              return updated;
            })
          );
        } catch {
          /* transient poll failure — next tick retries */
        }
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [queue]);

  const pendingCount = queue.filter((q) => !q.taskId).length;

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-sky-400" />
            Magnific Generative Upscaler
            <span className="text-xs font-mono font-medium px-2 py-0.5 rounded bg-sky-950/70 border border-sky-800/80 text-sky-300">
              Live • /api/upscale
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
          {/* Source image picker (wired to MinIO listing) */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-emerald-400" />
                Source Image
              </label>
              <button
                onClick={loadSources}
                className="text-slate-400 hover:text-sky-400 transition p-1"
                title="Refresh library images"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${loadingSources ? 'animate-spin' : ''}`} />
              </button>
            </div>
            <select
              data-testid="upscale-source-select"
              value={selectedPath}
              onChange={(e) => setSelectedPath(e.target.value)}
              className="w-full bg-slate-950 border border-slate-700 rounded-lg p-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
            >
              <option value="">
                {loadingSources ? 'Loading library…' : 'Choose an image from your library…'}
              </option>
              {sources.map((s) => (
                <option key={s.path} value={s.path}>
                  {s.name}
                </option>
              ))}
            </select>
            {!loadingSources && sources.length === 0 && (
              <p className="text-[11px] text-slate-500">
                No images found — upload one in the Media Library tab first.
              </p>
            )}
            {selectedSource?.url && (
              /* eslint-disable-next-line @next/next/no-img-element */
              <img
                src={selectedSource.url}
                alt={selectedSource.name}
                className="w-full h-28 object-cover rounded-lg border border-slate-700"
              />
            )}
          </div>

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
                  data-testid={`variant-preset-${p}`}
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
            <p className="text-[11px] text-slate-400">{presetDescription}</p>
          </div>

          {/* Content Categories */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
              <Wand2 className="w-3.5 h-3.5 text-indigo-400" />
              Content Category (v1 Core)
            </label>
            <div className="grid grid-cols-2 gap-2">
              {categoryEntries.map((cat) => (
                <button
                  key={cat.id}
                  data-testid={`variant-category-${cat.id}`}
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

          {error && (
            <p className="text-xs text-rose-400 flex items-center gap-1.5" data-testid="upscale-error">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </p>
          )}

          {/* Action CTAs */}
          <div className="flex items-center gap-3">
            <button
              data-testid="upscale-now"
              onClick={handleUpscaleNow}
              disabled={busy}
              className="flex-1 py-2.5 px-4 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white rounded-lg text-xs font-bold transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2"
            >
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5 fill-current" />}
              Upscale Now ({scale})
            </button>
            <button
              data-testid="upscale-queue-add"
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

            {compare ? (
              <CompareSlider
                beforeUrl={compare.beforeUrl}
                afterUrl={compare.afterUrl}
                beforeLabel={compare.beforeLabel}
                afterLabel={compare.afterLabel}
                aspectRatio="aspect-[16/10]"
              />
            ) : (
              <div className="aspect-[16/10] border border-dashed border-slate-700 rounded-xl bg-slate-900/40 flex flex-col items-center justify-center text-center p-6">
                <Sparkles className="w-8 h-8 text-slate-600 mb-2" />
                <p className="text-sm text-slate-400 font-medium">
                  No completed upscale yet
                </p>
                <p className="text-xs text-slate-500 mt-1 max-w-sm">
                  Pick a source image, run an upscale, and the real before/after comparison will
                  render here with signed S3 URLs.
                </p>
              </div>
            )}

            {/* Canvas Info Strip */}
            <div className="flex items-center justify-between px-3 py-2 bg-slate-900/60 border border-slate-800/80 rounded-lg text-[11px] text-slate-400 font-mono">
              <div>Engine: SDXL + ControlNet-Tile • Feather Blend • up to 8K</div>
              <div>
                Denoise: {mapCreativityToDenoise(sliders.creativity)} • ControlNet:{' '}
                {mapResemblanceToControlNet(sliders.resemblance)}
              </div>
            </div>
          </div>

          {/* Bulk Queue Tray */}
          <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold text-slate-200 flex items-center gap-1.5">
                <Layers className="w-3.5 h-3.5 text-sky-400" />
                Upscale Queue ({queue.length}/{MAX_BULK_QUEUE} items)
              </h3>
              <div className="flex items-center gap-3">
                {pendingCount > 0 && (
                  <button
                    data-testid="upscale-start-bulk"
                    onClick={handleStartBulk}
                    disabled={busy}
                    className="text-[11px] text-emerald-400 hover:text-emerald-300 font-semibold flex items-center gap-1 disabled:opacity-50"
                  >
                    {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3 fill-current" />}
                    Start Bulk ({pendingCount})
                  </button>
                )}
                <button
                  onClick={() => setQueue([])}
                  className="text-[11px] text-slate-400 hover:text-rose-400 transition"
                >
                  Clear all
                </button>
              </div>
            </div>

            <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
              {queue.length === 0 && (
                <p className="text-xs text-slate-500 py-4 text-center">
                  Queue is empty — add sources with <span className="font-semibold">Queue</span>{' '}
                  or dispatch one directly with <span className="font-semibold">Upscale Now</span>.
                </p>
              )}
              {queue.map((item) => (
                <div
                  key={item.id}
                  className="flex items-center gap-3 p-2.5 bg-slate-950/60 border border-slate-800 rounded-lg text-xs"
                >
                  {item.previewUrl ? (
                    /* eslint-disable-next-line @next/next/no-img-element */
                    <img
                      src={item.previewUrl}
                      alt={item.name}
                      className="w-10 h-10 rounded object-cover border border-slate-700 flex-shrink-0"
                    />
                  ) : (
                    <div className="w-10 h-10 rounded bg-slate-800 border border-slate-700 flex-shrink-0" />
                  )}

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
                      <button
                        onClick={() =>
                          item.resultUrl &&
                          setCompare({
                            beforeUrl: item.previewUrl,
                            afterUrl: item.resultUrl,
                            beforeLabel: `Original 1x — ${item.name}`,
                            afterLabel: `Upscaled ${item.targetScale} • SDXL-Tile (${item.preset})`,
                          })
                        }
                        className="flex items-center gap-1 text-[11px] text-emerald-400 font-medium hover:text-emerald-300"
                        title="Open in compare view"
                      >
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Compare
                      </button>
                    )}
                    {item.status === 'queued' && (
                      <span className="flex items-center gap-1 text-[11px] text-slate-400">
                        <Clock className="w-3.5 h-3.5" />
                        {item.taskId ? 'Queued' : 'Pending'}
                      </span>
                    )}
                    {item.status === 'diffusing' && (
                      <span className="text-[11px] text-sky-400 font-mono font-bold">
                        {item.progress}%
                      </span>
                    )}
                    {item.status === 'error' && (
                      <span className="text-[11px] text-rose-400 font-semibold">Failed</span>
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
