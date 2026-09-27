'use client';

// PROTOTYPE: Variant A - Slide-over Panel (Wayfinder #117 / Grilling #115)
// Structural variant: Right-hand slide-over drawer with tier options, fake processing state,
// checkerboard cut-out preview, and Accept/Reject in the panel footer.
// Inline progress indicator is reflected back to the originating asset row.

import React, { useState, useEffect } from 'react';
import {
  X,
  Sparkles,
  Layers,
  Zap,
  CheckCircle2,
  Trash2,
  Loader2,
  Info,
  Sliders,
  FileCheck,
  RefreshCw,
} from 'lucide-react';
import { StorageItem } from '../../utils/api';
import { BG_REMOVE_TIERS, BgRemoveTier } from './types';
import CutoutPreview from './CutoutPreview';

interface PanelVariantProps {
  target: StorageItem | null;
  onClose: () => void;
  onAccept: (derivative: StorageItem) => void;
  onReject: () => void;
  onProcessingStateChange?: (targetPath: string | null, percent: number) => void;
}

export default function PanelVariant({
  target,
  onClose,
  onAccept,
  onReject,
  onProcessingStateChange,
}: PanelVariantProps) {
  const [tier, setTier] = useState<BgRemoveTier>('u2net');
  const [status, setStatus] = useState<'idle' | 'processing' | 'preview'>('idle');
  const [progress, setProgress] = useState<number>(0);
  const [stepMessage, setStepMessage] = useState<string>('');

  // Reset when target changes
  useEffect(() => {
    if (target) {
      setStatus('idle');
      setProgress(0);
      setStepMessage('');
      onProcessingStateChange?.(null, 0);
    }
  }, [target, onProcessingStateChange]);

  if (!target) return null;

  const baseName = target.name.replace(/\.[^/.]+$/, '');
  const derivativeName = `${baseName}_nobg.png`;

  const handleStartProcessing = () => {
    setStatus('processing');
    setProgress(15);
    setStepMessage('Loading neural model weights (' + BG_REMOVE_TIERS[tier].label + ')...');
    onProcessingStateChange?.(target.path, 15);

    setTimeout(() => {
      setProgress(55);
      setStepMessage('Estimating salient foreground mask & depth boundaries...');
      onProcessingStateChange?.(target.path, 55);
    }, 550);

    setTimeout(() => {
      setProgress(85);
      setStepMessage('Generating RGBA alpha matte & compositing cut-out...');
      onProcessingStateChange?.(target.path, 85);
    }, 1100);

    setTimeout(() => {
      setProgress(100);
      setStatus('preview');
      setStepMessage('Cut-out complete. Review preview before saving.');
      onProcessingStateChange?.(null, 100);
    }, 1500);
  };

  const handleAccept = () => {
    const derivative: StorageItem = {
      name: derivativeName,
      path: target.path.replace(/[^/]+$/, derivativeName),
      type: 'file',
      size: Math.round((target.size ?? 1500000) * 0.72),
      last_modified: new Date().toISOString(),
      url: target.url,
    };
    onAccept(derivative);
    onClose();
  };

  const handleReject = () => {
    onReject();
    onClose();
  };

  return (
    <aside
      aria-label="Remove Background Panel"
      className="fixed inset-y-0 right-0 z-50 w-full sm:w-[460px] bg-slate-900 border-l border-slate-700/80 shadow-2xl flex flex-col transition-all duration-300 animate-in slide-in-from-right"
    >
      {/* Panel Header */}
      <div className="p-4 border-b border-slate-800 flex items-center justify-between bg-slate-950/70">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-sky-950 border border-sky-800/80 text-sky-400">
            <Sparkles className="w-4 h-4" />
          </div>
          <div>
            <h3 className="font-semibold text-sm text-slate-100 flex items-center gap-2">
              Remove Background
              <span className="text-[10px] uppercase font-bold text-sky-400 bg-sky-950 border border-sky-800 px-1.5 py-0.2 rounded">
                Variant A: Panel
              </span>
            </h3>
            <p className="text-[11px] text-slate-400 truncate max-w-[260px] font-mono">
              {target.name}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition"
          aria-label="Close panel"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Panel Body */}
      <div className="flex-1 overflow-y-auto p-5 space-y-5">
        {/* Target Asset Summary */}
        <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-3 flex items-center gap-3">
          <div className="w-14 h-14 rounded-md overflow-hidden bg-slate-900 border border-slate-700/60 flex-shrink-0">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={target.url || ''}
              alt={target.name}
              className="w-full h-full object-cover"
            />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-slate-200 truncate">{target.name}</p>
            <div className="flex items-center gap-2 mt-1 text-[11px] text-slate-400">
              <span>Original: {target.size ? `${Math.round(target.size / 1024)} KB` : '—'}</span>
              <span>•</span>
              <span className="text-sky-400">Output: PNG RGBA</span>
            </div>
            <p className="text-[10px] text-slate-500 mt-0.5 truncate font-mono">
              → {derivativeName}
            </p>
          </div>
        </div>

        {/* Tier Selector */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-sky-400" />
              Segmentation Model Tier
            </label>
            <span className="text-[10px] text-slate-400">Binding Decision #115</span>
          </div>

          <div className="grid grid-cols-2 gap-2">
            {(['u2net', 'birefnet'] as BgRemoveTier[]).map((tId) => {
              const cfg = BG_REMOVE_TIERS[tId];
              const isSelected = tier === tId;
              return (
                <button
                  key={tId}
                  disabled={status === 'processing'}
                  onClick={() => setTier(tId)}
                  className={`p-3 rounded-lg border text-left transition flex flex-col justify-between ${
                    isSelected
                      ? 'border-sky-500 bg-sky-950/40 text-slate-100 ring-1 ring-sky-500/50'
                      : 'border-slate-800 bg-slate-950 hover:bg-slate-850 text-slate-400'
                  }`}
                >
                  <div className="flex items-center justify-between w-full mb-1">
                    <span className="font-semibold text-xs text-slate-200 flex items-center gap-1">
                      {tId === 'u2net' ? <Zap className="w-3.5 h-3.5 text-amber-400" /> : <Layers className="w-3.5 h-3.5 text-emerald-400" />}
                      {tId === 'u2net' ? 'Fast' : 'Quality'}
                    </span>
                    <span className={`text-[9px] px-1.5 py-0.2 rounded font-mono ${
                      tId === 'u2net' ? 'bg-amber-950/60 text-amber-300 border border-amber-800/40' : 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/40'
                    }`}>
                      {cfg.badge}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400 line-clamp-2 mt-1">
                    {cfg.description}
                  </p>
                  <div className="mt-2 text-[9px] text-slate-500 font-mono flex items-center justify-between">
                    <span>{cfg.inferenceTime}</span>
                    <span>{cfg.vram}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Processing State */}
        {status === 'processing' && (
          <div className="bg-slate-950 border border-sky-900/60 rounded-xl p-4 space-y-3 animate-in fade-in">
            <div className="flex items-center justify-between text-xs">
              <span className="text-slate-300 font-medium flex items-center gap-2">
                <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                Processing cut-out with {BG_REMOVE_TIERS[tier].label}...
              </span>
              <span className="font-mono text-sky-400 font-semibold">{progress}%</span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-sky-500 h-full transition-all duration-300 ease-out"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-[11px] text-slate-400 font-mono flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-ping" />
              {stepMessage}
            </p>
          </div>
        )}

        {/* Preview State: Checkerboard Cut-out */}
        {status === 'preview' && (
          <div className="space-y-3 animate-in fade-in">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-slate-200 flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                Cut-out Result Preview
              </label>
              <span className="text-[10px] text-emerald-400 bg-emerald-950/70 border border-emerald-800/80 px-2 py-0.5 rounded-full">
                Transparent RGBA
              </span>
            </div>

            <div className="w-full h-64 border border-slate-700/80 rounded-lg overflow-hidden shadow-inner">
              <CutoutPreview imageUrl={target.url} alt={target.name} mode="cutout" className="w-full h-full" />
            </div>

            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs space-y-1.5 text-slate-400">
              <div className="flex items-center gap-1.5 text-slate-200 font-medium">
                <FileCheck className="w-3.5 h-3.5 text-sky-400" />
                Additive Derivative Flow
              </div>
              <p className="text-[11px]">
                Accepting creates <span className="font-mono text-sky-300 font-semibold">{derivativeName}</span> without altering the original image. Re-running will produce a sibling derivative.
              </p>
            </div>
          </div>
        )}

        {/* Idle notice */}
        {status === 'idle' && (
          <div className="border border-slate-800/90 rounded-lg p-4 bg-slate-950/50 space-y-2 text-xs text-slate-400">
            <div className="flex items-center gap-1.5 text-slate-300 font-semibold">
              <Info className="w-3.5 h-3.5 text-sky-400" />
              Preview-before-accept Workflow
            </div>
            <p className="text-[11px] leading-relaxed">
              Clicking <strong className="text-slate-200">Run Background Removal</strong> executes on-demand matte isolation. You can inspect the transparent cut-out on the checkerboard before deciding to save or discard.
            </p>
          </div>
        )}
      </div>

      {/* Panel Footer */}
      <div className="p-4 border-t border-slate-800 bg-slate-950/90 flex gap-2">
        {status === 'idle' && (
          <>
            <button
              onClick={onClose}
              className="flex-1 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition border border-slate-700"
            >
              Cancel
            </button>
            <button
              onClick={handleStartProcessing}
              className="flex-[2] py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow-lg shadow-sky-950"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Run Background Removal
            </button>
          </>
        )}

        {status === 'processing' && (
          <button
            disabled
            className="w-full py-2 bg-slate-800/80 text-slate-400 rounded-lg text-xs font-semibold transition flex items-center justify-center gap-2 cursor-wait"
          >
            <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
            Generating Matte...
          </button>
        )}

        {status === 'preview' && (
          <>
            <button
              onClick={handleReject}
              className="flex-1 py-2 bg-slate-800/80 hover:bg-rose-950/60 hover:text-rose-300 text-slate-300 rounded-lg text-xs font-semibold transition border border-slate-700 flex items-center justify-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Reject & Discard
            </button>
            <button
              onClick={handleAccept}
              className="flex-[2] py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-1.5 shadow-lg shadow-emerald-950"
            >
              <CheckCircle2 className="w-3.5 h-3.5" />
              Accept & Save Derivative
            </button>
          </>
        )}
      </div>
    </aside>
  );
}
