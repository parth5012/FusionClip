'use client';

// PROTOTYPE: CutoutPreview Component (Wayfinder #117 / Grilling #115)
// Throwaway SVG/CSS mask renderer displaying RGBA cut-out over dark checkerboard pattern.

import React from 'react';
import { InlineViewMode } from './types';

interface CutoutPreviewProps {
  imageUrl?: string;
  alt: string;
  mode?: InlineViewMode;
  className?: string;
}

export const CHECKERBOARD_STYLE: React.CSSProperties = {
  backgroundColor: '#0f172a',
  backgroundImage: `
    linear-gradient(45deg, #1e293b 25%, transparent 25%),
    linear-gradient(-45deg, #1e293b 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #1e293b 75%),
    linear-gradient(-45deg, transparent 75%, #1e293b 75%)
  `,
  backgroundSize: '16px 16px',
  backgroundPosition: '0 0, 0 8px, 8px -8px, -8px 0px',
};

export default function CutoutPreview({
  imageUrl,
  alt,
  mode = 'cutout',
  className = '',
}: CutoutPreviewProps) {
  const fallbackPlaceholder = (
    <div className="w-full h-full flex flex-col items-center justify-center p-6 text-slate-500">
      <div className="w-16 h-16 rounded-xl border border-slate-700/60 bg-slate-800/40 flex items-center justify-center mb-2">
        <svg className="w-8 h-8 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
        </svg>
      </div>
      <p className="text-xs font-mono">{alt}</p>
    </div>
  );

  if (!imageUrl) {
    return (
      <div className={`relative overflow-hidden rounded-lg ${className}`} style={CHECKERBOARD_STYLE}>
        {fallbackPlaceholder}
      </div>
    );
  }

  // 1. Raw Original
  if (mode === 'original') {
    return (
      <div className={`relative overflow-hidden rounded-lg bg-slate-950 flex items-center justify-center ${className}`}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={alt}
          className="max-h-full max-w-full object-contain"
        />
        <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-slate-900/80 backdrop-blur-sm border border-slate-700 text-[10px] font-mono text-slate-300">
          Original RGBA
        </div>
      </div>
    );
  }

  // 2. Mask Overlay (Ruby / Neon Alpha Matte over original)
  if (mode === 'mask') {
    return (
      <div className={`relative overflow-hidden rounded-lg bg-slate-950 flex items-center justify-center ${className}`}>
        {/* Base Image */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={alt}
          className="max-h-full max-w-full object-contain"
        />

        {/* Mask Alpha Matte Overlay */}
        <div
          className="absolute inset-0 pointer-events-none mix-blend-screen opacity-85"
          style={{
            background: 'radial-gradient(ellipse 65% 72% at 50% 50%, rgba(16, 185, 129, 0.45) 45%, rgba(16, 185, 129, 0.1) 68%, transparent 75%)',
          }}
        />

        {/* Inverted Background Area tint */}
        <div
          className="absolute inset-0 pointer-events-none mix-blend-multiply opacity-70"
          style={{
            background: 'radial-gradient(ellipse 65% 72% at 50% 50%, transparent 48%, rgba(244, 63, 94, 0.5) 65%, rgba(225, 29, 72, 0.75) 85%)',
          }}
        />

        <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-emerald-950/80 backdrop-blur-sm border border-emerald-700/80 text-[10px] font-mono text-emerald-300 flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
          Alpha Matte Overlay
        </div>
      </div>
    );
  }

  // 3. Cut-out on Checkerboard (Transparent PNG RGBA)
  return (
    <div
      className={`relative overflow-hidden rounded-lg flex items-center justify-center ${className}`}
      style={CHECKERBOARD_STYLE}
    >
      {/* Cut-out image with CSS silhouette mask simulating transparent cut-out */}
      <div
        className="relative max-h-full max-w-full flex items-center justify-center"
        style={{
          WebkitMaskImage: 'radial-gradient(ellipse 62% 70% at 50% 50%, black 50%, rgba(0, 0, 0, 0.9) 62%, transparent 74%)',
          maskImage: 'radial-gradient(ellipse 62% 70% at 50% 50%, black 50%, rgba(0, 0, 0, 0.9) 62%, transparent 74%)',
        }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={imageUrl}
          alt={alt}
          className="max-h-full max-w-full object-contain drop-shadow-[0_10px_20px_rgba(0,0,0,0.5)]"
        />
      </div>

      <div className="absolute top-2 left-2 px-2 py-0.5 rounded bg-slate-900/85 backdrop-blur-sm border border-sky-600/60 text-[10px] font-mono text-sky-300 flex items-center gap-1.5">
        <span className="w-1.5 h-1.5 rounded-full bg-sky-400" />
        PNG RGBA (Transparent)
      </div>
    </div>
  );
}
