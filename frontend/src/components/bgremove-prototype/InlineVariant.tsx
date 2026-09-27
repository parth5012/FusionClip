'use client';

// PROTOTYPE: Variant C - Inline Preview Strip (Wayfinder #117 / Grilling #115)
// No modal or slide-over drawer: clicking the row action expands an inline preview strip
// directly beneath the asset row with 3-way view toggle (Original | Mask overlay | Cut-out on checkerboard)
// and inline Accept/Reject buttons.

import React, { useState } from 'react';
import {
  Sparkles,
  Zap,
  Layers,
  CheckCircle2,
  Trash2,
  Loader2,
  X,
  Eye,
  Sliders,
  FileCheck,
} from 'lucide-react';
import { StorageItem } from '../../utils/api';
import { BG_REMOVE_TIERS, BgRemoveTier, InlineViewMode } from './types';
import CutoutPreview from './CutoutPreview';

interface InlineVariantStripProps {
  target: StorageItem;
  onClose: () => void;
  onAccept: (derivative: StorageItem) => void;
  onReject: () => void;
}

export default function InlineVariantStrip({
  target,
  onClose,
  onAccept,
  onReject,
}: InlineVariantStripProps) {
  const [tier, setTier] = useState<BgRemoveTier>('u2net');
  const [status, setStatus] = useState<'idle' | 'processing' | 'preview'>('idle');
  const [viewMode, setViewMode] = useState<InlineViewMode>('cutout');
  const [progress, setProgress] = useState<number>(0);

  const baseName = target.name.replace(/\.[^/.]+$/, '');
  const derivativeName = `${baseName}_nobg.png`;

  const handleStartProcessing = () => {
    setStatus('processing');
    setProgress(15);

    setTimeout(() => {
      setProgress(55);
    }, 500);

    setTimeout(() => {
      setProgress(85);
    }, 1000);

    setTimeout(() => {
      setProgress(100);
      setStatus('preview');
      setViewMode('cutout');
    }, 1500);
  };

  const handleAccept = () => {
    const derivative: StorageItem = {
      name: derivativeName,
      path: target.path.replace(/[^/]+$/, derivativeName),
      type: 'file',
      size: Math.round((target.size ?? 1500000) * 0.7),
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
    <div
      data-testid="inline-bgremove-strip"
      className="col-span-1 md:col-span-12 bg-slate-950 border-y-2 border-sky-500/60 p-4 sm:p-5 text-sm space-y-4 shadow-2xl transition-all"
    >
      {/* Strip Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 pb-3">
        <div className="flex items-center gap-2">
          <div className="p-1 rounded bg-sky-950 border border-sky-800 text-sky-400">
            <Sparkles className="w-3.5 h-3.5" />
          </div>
          <span className="font-bold text-xs text-slate-100 flex items-center gap-1.5">
            Inline Background Removal
            <span className="text-[10px] uppercase font-bold text-sky-400 bg-sky-950 border border-sky-800 px-1.5 py-0.2 rounded">
              Variant C: Inline Strip
            </span>
          </span>
          <span className="text-xs font-mono text-slate-400">
            ({target.name})
          </span>
        </div>

        <div className="flex items-center gap-2">
          {/* Output notice */}
          <span className="text-[11px] text-slate-400 hidden sm:inline">
            Saves additive derivative <span className="font-mono text-sky-300">{derivativeName}</span>
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition"
            aria-label="Close inline preview strip"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Strip Content Grid */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-5 items-start">
        {/* Left: Controls & Tier Selection */}
        <div className="col-span-1 md:col-span-4 space-y-3">
          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-slate-300 flex items-center gap-1">
              <Sliders className="w-3 h-3 text-sky-400" /> Model Tier:
            </label>
            <div className="grid grid-cols-2 gap-2">
              <button
                disabled={status === 'processing'}
                onClick={() => setTier('u2net')}
                className={`p-2 rounded-lg border text-left transition ${
                  tier === 'u2net'
                    ? 'border-sky-500 bg-sky-950/40 text-slate-100 ring-1 ring-sky-500'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:bg-slate-850'
                }`}
              >
                <div className="flex items-center justify-between text-xs font-bold">
                  <span className="flex items-center gap-1">
                    <Zap className="w-3 h-3 text-amber-400" /> Fast
                  </span>
                  <span className="text-[9px] font-mono text-amber-400">u2net</span>
                </div>
                <p className="text-[10px] text-slate-400 mt-1 line-clamp-1">
                  ~0.8s inference
                </p>
              </button>

              <button
                disabled={status === 'processing'}
                onClick={() => setTier('birefnet')}
                className={`p-2 rounded-lg border text-left transition ${
                  tier === 'birefnet'
                    ? 'border-sky-500 bg-sky-950/40 text-slate-100 ring-1 ring-sky-500'
                    : 'border-slate-800 bg-slate-900 text-slate-400 hover:bg-slate-850'
                }`}
              >
                <div className="flex items-center justify-between text-xs font-bold">
                  <span className="flex items-center gap-1">
                    <Layers className="w-3 h-3 text-emerald-400" /> Quality
                  </span>
                  <span className="text-[9px] font-mono text-emerald-400">birefnet</span>
                </div>
                <p className="text-[10px] text-slate-400 mt-1 line-clamp-1">
                  High-precision edges
                </p>
              </button>
            </div>
          </div>

          {/* Trigger button (when idle) */}
          {status === 'idle' && (
            <div className="space-y-2 pt-1">
              <button
                onClick={handleStartProcessing}
                className="w-full py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow-md shadow-sky-950"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Remove Background ({tier === 'u2net' ? 'Fast' : 'Quality'})
              </button>
              <p className="text-[11px] text-slate-500">
                Executes without leaving page table view.
              </p>
            </div>
          )}

          {/* Processing Indicator */}
          {status === 'processing' && (
            <div className="bg-slate-900 border border-sky-900 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between text-xs text-slate-300">
                <span className="flex items-center gap-1.5">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-sky-400" />
                  Extracting alpha matte...
                </span>
                <span className="font-mono text-sky-400">{progress}%</span>
              </div>
              <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-sky-500 h-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Accept / Reject actions (when in preview mode) */}
          {status === 'preview' && (
            <div className="space-y-2 pt-1">
              <button
                onClick={handleAccept}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center justify-center gap-2 shadow-lg shadow-emerald-950"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Accept & Save Derivative
              </button>

              <button
                onClick={handleReject}
                className="w-full py-1.5 bg-slate-900 hover:bg-rose-950/60 hover:text-rose-300 text-slate-300 rounded-lg text-xs font-medium transition border border-slate-800 flex items-center justify-center gap-1.5"
              >
                <Trash2 className="w-3.5 h-3.5" />
                Discard Cut-out
              </button>
            </div>
          )}
        </div>

        {/* Right: 3-way view toggle & Preview viewport */}
        <div className="col-span-1 md:col-span-8 space-y-2">
          {/* 3-way view toggle */}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1 bg-slate-900 p-1 rounded-lg border border-slate-800">
              <span className="text-[11px] text-slate-400 px-2 flex items-center gap-1">
                <Eye className="w-3 h-3 text-slate-400" /> View:
              </span>
              {(
                [
                  { id: 'original', label: '1. Original' },
                  { id: 'mask', label: '2. Mask Overlay' },
                  { id: 'cutout', label: '3. Cut-out (Checkerboard)' },
                ] as const
              ).map((v) => (
                <button
                  key={v.id}
                  disabled={status !== 'preview'}
                  onClick={() => setViewMode(v.id)}
                  className={`px-2.5 py-1 rounded text-xs font-medium transition ${
                    viewMode === v.id && status === 'preview'
                      ? 'bg-sky-500 text-slate-950 font-bold shadow-sm'
                      : status !== 'preview'
                      ? 'text-slate-600 cursor-not-allowed'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {v.label}
                </button>
              ))}
            </div>

            {status === 'preview' && (
              <span className="text-[11px] text-emerald-400 font-mono flex items-center gap-1">
                <FileCheck className="w-3 h-3" /> Output: PNG RGBA
              </span>
            )}
          </div>

          {/* Viewport display */}
          <div className="w-full h-56 sm:h-64 rounded-xl border border-slate-800 overflow-hidden shadow-inner bg-slate-950 flex items-center justify-center">
            {status === 'idle' ? (
              <div className="text-center p-6 text-slate-500 space-y-1">
                <p className="text-xs">Original image selected: {target.name}</p>
                <p className="text-[11px] text-slate-600">
                  Select model tier on the left and click &apos;Remove Background&apos; to preview.
                </p>
              </div>
            ) : (
              <CutoutPreview
                imageUrl={target.url}
                alt={target.name}
                mode={status === 'preview' ? viewMode : 'original'}
                className="w-full h-full"
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
