'use client';

// PROTOTYPE: Variant B - Centered Modal Wizard (Wayfinder #117 / Grilling #115)
// Matches existing Upscale modal precedent (FileManager.tsx:871-946).
// Step 1: Options -> Step 2: Processing progress -> Step 3: Split before/after slider + Accept/Reject.

import React, { useState, useEffect, useRef } from 'react';
import {
  X,
  Sparkles,
  Zap,
  Layers,
  ArrowRight,
  ArrowLeft,
  CheckCircle2,
  Trash2,
  Loader2,
  FileCheck,
  SplitSquareVertical,
} from 'lucide-react';
import { StorageItem } from '../../utils/api';
import { BG_REMOVE_TIERS, BgRemoveTier } from './types';
import { CHECKERBOARD_STYLE } from './CutoutPreview';

interface ModalVariantProps {
  target: StorageItem | null;
  onClose: () => void;
  onAccept: (derivative: StorageItem) => void;
  onReject: () => void;
}

type WizardStep = 1 | 2 | 3;

export default function ModalVariant({
  target,
  onClose,
  onAccept,
  onReject,
}: ModalVariantProps) {
  const [step, setStep] = useState<WizardStep>(1);
  const [tier, setTier] = useState<BgRemoveTier>('u2net');
  const [progress, setProgress] = useState<number>(0);
  const [stepMessage, setStepMessage] = useState<string>('');
  const [sliderPosition, setSliderPosition] = useState<number>(50); // 0-100 %
  const sliderContainerRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef<boolean>(false);

  useEffect(() => {
    if (target) {
      setStep(1);
      setProgress(0);
      setStepMessage('');
      setSliderPosition(50);
    }
  }, [target]);

  if (!target) return null;

  const baseName = target.name.replace(/\.[^/.]+$/, '');
  const derivativeName = `${baseName}_nobg.png`;

  const handleStartProcessing = () => {
    setStep(2);
    setProgress(10);
    setStepMessage('Allocating inference worker for ' + BG_REMOVE_TIERS[tier].label + '...');

    setTimeout(() => {
      setProgress(48);
      setStepMessage('Estimating trimap and edge probabilities...');
    }, 450);

    setTimeout(() => {
      setProgress(82);
      setStepMessage('Compositing transparent RGBA cut-out...');
    }, 950);

    setTimeout(() => {
      setProgress(100);
      setStep(3);
    }, 1500);
  };

  const handleAccept = () => {
    const derivative: StorageItem = {
      name: derivativeName,
      path: target.path.replace(/[^/]+$/, derivativeName),
      type: 'file',
      size: Math.round((target.size ?? 1500000) * 0.75),
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

  // Draggable comparison slider handlers
  const handleSliderMove = (clientX: number) => {
    if (!sliderContainerRef.current) return;
    const rect = sliderContainerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(clientX - rect.left, rect.width));
    const percent = Math.round((x / rect.width) * 100);
    setSliderPosition(percent);
  };

  const handleMouseDown = () => {
    isDraggingRef.current = true;
  };

  const handleMouseMove = (e: React.MouseEvent) => {
    if (isDraggingRef.current) {
      handleSliderMove(e.clientX);
    }
  };

  const handleMouseUp = () => {
    isDraggingRef.current = false;
  };

  return (
    <div
      data-testid="bgremove-modal-wizard"
      className="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in"
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
    >
      <div className="bg-slate-900 border border-slate-700/80 rounded-2xl w-full max-w-2xl overflow-hidden shadow-2xl flex flex-col max-h-[92vh]">
        {/* Modal Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-lg bg-sky-950/80 border border-sky-800 text-sky-400">
              <Sparkles className="w-4 h-4" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-sm text-slate-100">
                  Background Removal Wizard
                </h3>
                <span className="text-[10px] uppercase font-bold text-sky-400 bg-sky-950 border border-sky-800 px-1.5 py-0.2 rounded">
                  Variant B: Modal
                </span>
              </div>
              <p className="text-[11px] text-slate-400 font-mono mt-0.5 truncate max-w-sm">
                {target.name}
              </p>
            </div>
          </div>

          {/* Step Indicator */}
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-400">
            <span
              className={`px-2 py-0.5 rounded-full font-mono text-[10px] ${
                step === 1 ? 'bg-sky-600 text-white font-bold' : 'bg-slate-800 text-slate-400'
              }`}
            >
              1. Options
            </span>
            <ArrowRight className="w-3 h-3 text-slate-600" />
            <span
              className={`px-2 py-0.5 rounded-full font-mono text-[10px] ${
                step === 2 ? 'bg-sky-600 text-white font-bold' : 'bg-slate-800 text-slate-400'
              }`}
            >
              2. Processing
            </span>
            <ArrowRight className="w-3 h-3 text-slate-600" />
            <span
              className={`px-2 py-0.5 rounded-full font-mono text-[10px] ${
                step === 3 ? 'bg-emerald-600 text-white font-bold' : 'bg-slate-800 text-slate-400'
              }`}
            >
              3. Compare & Accept
            </span>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-white hover:bg-slate-800 transition"
            aria-label="Close modal"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body: Switch by step */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* STEP 1: OPTIONS */}
          {step === 1 && (
            <div className="space-y-5 animate-in fade-in">
              {/* Asset Snapshot */}
              <div className="flex items-center gap-4 bg-slate-950 border border-slate-800 rounded-xl p-3">
                <div className="w-16 h-16 rounded-lg bg-slate-900 overflow-hidden flex-shrink-0 border border-slate-700">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={target.url || ''}
                    alt={target.name}
                    className="w-full h-full object-cover"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-semibold text-slate-200 truncate">{target.name}</p>
                  <p className="text-xs text-slate-400 mt-0.5 font-mono">{target.path}</p>
                  <p className="text-[11px] text-sky-400 mt-1 font-medium">
                    Output target: <span className="font-mono text-slate-300">{derivativeName}</span> (PNG RGBA)
                  </p>
                </div>
              </div>

              {/* Tier Selection */}
              <div className="space-y-2">
                <label className="text-xs font-semibold text-slate-200 block">
                  Select Segmentation Engine
                </label>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Fast u2net */}
                  <button
                    type="button"
                    onClick={() => setTier('u2net')}
                    className={`p-4 rounded-xl border text-left transition flex flex-col justify-between ${
                      tier === 'u2net'
                        ? 'border-sky-500 bg-sky-950/40 ring-1 ring-sky-500 text-slate-100'
                        : 'border-slate-800 bg-slate-950 hover:bg-slate-850 text-slate-400'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="font-bold text-sm text-slate-200 flex items-center gap-1.5">
                          <Zap className="w-4 h-4 text-amber-400" />
                          Fast (U²-Net)
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded font-mono bg-amber-950/80 text-amber-300 border border-amber-800/60">
                          Default
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">
                        {BG_REMOVE_TIERS.u2net.description}
                      </p>
                    </div>
                    <div className="mt-3 pt-2 border-t border-slate-800/80 text-[10px] font-mono text-slate-400 flex justify-between">
                      <span>Speed: {BG_REMOVE_TIERS.u2net.inferenceTime}</span>
                      <span>VRAM: {BG_REMOVE_TIERS.u2net.vram}</span>
                    </div>
                  </button>

                  {/* Quality birefnet */}
                  <button
                    type="button"
                    onClick={() => setTier('birefnet')}
                    className={`p-4 rounded-xl border text-left transition flex flex-col justify-between ${
                      tier === 'birefnet'
                        ? 'border-sky-500 bg-sky-950/40 ring-1 ring-sky-500 text-slate-100'
                        : 'border-slate-800 bg-slate-950 hover:bg-slate-850 text-slate-400'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="font-bold text-sm text-slate-200 flex items-center gap-1.5">
                          <Layers className="w-4 h-4 text-emerald-400" />
                          Quality (BiRefNet)
                        </span>
                        <span className="text-[10px] px-2 py-0.5 rounded font-mono bg-emerald-950/80 text-emerald-300 border border-emerald-800/60">
                          High Precision
                        </span>
                      </div>
                      <p className="text-xs text-slate-400">
                        {BG_REMOVE_TIERS.birefnet.description}
                      </p>
                    </div>
                    <div className="mt-3 pt-2 border-t border-slate-800/80 text-[10px] font-mono text-slate-400 flex justify-between">
                      <span>Speed: {BG_REMOVE_TIERS.birefnet.inferenceTime}</span>
                      <span>VRAM: {BG_REMOVE_TIERS.birefnet.vram}</span>
                    </div>
                  </button>
                </div>
              </div>

              {/* Workflow Notice */}
              <div className="p-3 bg-slate-950/60 border border-slate-800 rounded-xl text-xs text-slate-400 flex items-start gap-2.5">
                <FileCheck className="w-4 h-4 text-sky-400 flex-shrink-0 mt-0.5" />
                <p>
                  Execution will generate a preview before committing to storage. The original asset remains untouched, and re-running creates a sibling derivative.
                </p>
              </div>
            </div>
          )}

          {/* STEP 2: PROCESSING PROGRESS */}
          {step === 2 && (
            <div className="py-12 flex flex-col items-center justify-center text-center space-y-6 animate-in fade-in">
              <div className="relative">
                <div className="w-20 h-20 rounded-full border-4 border-slate-800 border-t-sky-500 animate-spin flex items-center justify-center" />
                <div className="absolute inset-0 flex items-center justify-center font-mono text-sm font-bold text-sky-400">
                  {progress}%
                </div>
              </div>

              <div className="space-y-1.5 max-w-sm">
                <h4 className="text-sm font-semibold text-slate-200">
                  Extracting Alpha Matte
                </h4>
                <p className="text-xs font-mono text-slate-400">
                  {stepMessage}
                </p>
              </div>

              <div className="w-64 bg-slate-800 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-sky-500 h-full transition-all duration-300 ease-out"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* STEP 3: SPLIT BEFORE/AFTER COMPARISON SLIDER */}
          {step === 3 && (
            <div className="space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <SplitSquareVertical className="w-4 h-4 text-sky-400" />
                  <span className="text-xs font-semibold text-slate-200">
                    Split Comparison Slider (Drag handle to inspect alpha edges)
                  </span>
                </div>
                <span className="text-[10px] font-mono text-slate-400">
                  Left: Original | Right: Transparent Cut-out
                </span>
              </div>

              {/* Interactive Split Slider Container */}
              <div
                ref={sliderContainerRef}
                onMouseDown={handleMouseDown}
                className="relative w-full h-72 sm:h-80 rounded-xl overflow-hidden cursor-ew-resize select-none border border-slate-700 shadow-inner"
              >
                {/* Layer 1 (Right): Transparent Cut-out on Checkerboard */}
                <div
                  className="absolute inset-0 flex items-center justify-center"
                  style={CHECKERBOARD_STYLE}
                >
                  <div
                    className="relative max-h-full max-w-full flex items-center justify-center"
                    style={{
                      WebkitMaskImage: 'radial-gradient(ellipse 60% 70% at 50% 50%, black 50%, rgba(0, 0, 0, 0.9) 60%, transparent 72%)',
                      maskImage: 'radial-gradient(ellipse 60% 70% at 50% 50%, black 50%, rgba(0, 0, 0, 0.9) 60%, transparent 72%)',
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={target.url || ''}
                      alt="Cutout Preview"
                      className="max-h-72 max-w-full object-contain"
                    />
                  </div>
                  <div className="absolute top-2 right-2 px-2 py-0.5 rounded bg-slate-900/85 backdrop-blur-sm border border-sky-500/50 text-[10px] font-mono text-sky-300">
                    Cut-out (RGBA)
                  </div>
                </div>

                {/* Layer 2 (Left): Original Image clipped by slider position */}
                <div
                  className="absolute inset-0 overflow-hidden bg-slate-950 flex items-center justify-center pointer-events-none"
                  style={{ width: `${sliderPosition}%` }}
                >
                  <div
                    className="absolute inset-0 flex items-center justify-center"
                    style={{
                      width: sliderContainerRef.current ? sliderContainerRef.current.clientWidth : '100%',
                    }}
                  >
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={target.url || ''}
                      alt="Original Preview"
                      className="max-h-72 max-w-full object-contain"
                    />
                  </div>
                  <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-slate-900/85 backdrop-blur-sm border border-slate-700 text-[10px] font-mono text-slate-300">
                    Original
                  </div>
                </div>

                {/* Divider Line & Handle */}
                <div
                  className="absolute inset-y-0 w-0.5 bg-white shadow-[0_0_10px_rgba(0,0,0,0.8)] pointer-events-none"
                  style={{ left: `${sliderPosition}%` }}
                >
                  <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-7 h-7 rounded-full bg-white text-slate-900 shadow-xl flex items-center justify-center text-xs font-bold border-2 border-sky-500">
                    ↔
                  </div>
                </div>
              </div>

              {/* Derivative save reminder */}
              <div className="bg-slate-950/80 border border-slate-800 rounded-lg p-3 text-xs text-slate-400 flex items-center justify-between">
                <div>
                  <span className="text-slate-200 font-semibold">Planned Derivative: </span>
                  <span className="font-mono text-sky-400">{derivativeName}</span>
                </div>
                <span className="text-[11px] text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Ready to Save
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/90 flex justify-between items-center">
          {step === 1 && (
            <>
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-semibold transition border border-slate-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleStartProcessing}
                className="px-5 py-2 bg-sky-600 hover:bg-sky-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-sky-950"
              >
                <Sparkles className="w-3.5 h-3.5" />
                Proceed to Remove Background
              </button>
            </>
          )}

          {step === 2 && (
            <div className="w-full flex justify-center">
              <span className="text-xs text-slate-500 font-mono">
                Simulating model inference (~1.5s)...
              </span>
            </div>
          )}

          {step === 3 && (
            <>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setStep(1)}
                  className="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-medium transition border border-slate-700 flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" />
                  Re-configure
                </button>
                <button
                  type="button"
                  onClick={handleReject}
                  className="px-3 py-2 bg-slate-800/80 hover:bg-rose-950/60 hover:text-rose-300 text-slate-300 rounded-lg text-xs font-medium transition border border-slate-700 flex items-center gap-1.5"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Reject & Discard
                </button>
              </div>

              <button
                type="button"
                onClick={handleAccept}
                className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold transition flex items-center gap-2 shadow-lg shadow-emerald-950"
              >
                <CheckCircle2 className="w-3.5 h-3.5" />
                Accept & Save Cut-out (+1 Asset)
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
