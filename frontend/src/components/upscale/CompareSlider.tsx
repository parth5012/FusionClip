'use client';

import React, { useState, useRef, useCallback, useEffect } from 'react';
import { Sparkles, Image as ImageIcon, MoveHorizontal, Maximize2 } from 'lucide-react';

interface CompareSliderProps {
  beforeUrl?: string;
  afterUrl?: string;
  beforeLabel?: string;
  afterLabel?: string;
  aspectRatio?: string;
  className?: string;
}

export default function CompareSlider({
  beforeUrl = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=600&q=40',
  afterUrl = 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?auto=format&fit=crop&w=2400&q=95',
  beforeLabel = 'Original 1x (512x512)',
  afterLabel = 'Magnific 4x Enhanced (2048x2048)',
  aspectRatio = 'aspect-[4/3]',
  className = '',
}: CompareSliderProps) {
  const [sliderPosition, setSliderPosition] = useState(50); // percentage 0..100
  const [isDragging, setIsDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMove = useCallback(
    (clientX: number) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const x = clientX - rect.left;
      const pos = Math.max(0, Math.min(100, (x / rect.width) * 100));
      setSliderPosition(pos);
    },
    []
  );

  const handleMouseDown = (e: React.MouseEvent) => {
    setIsDragging(true);
    handleMove(e.clientX);
  };

  const handleTouchStart = (e: React.TouchEvent) => {
    setIsDragging(true);
    handleMove(e.touches[0].clientX);
  };

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        handleMove(e.clientX);
      }
    };
    const onMouseUp = () => setIsDragging(false);
    const onTouchMove = (e: TouchEvent) => {
      if (isDragging && e.touches[0]) {
        handleMove(e.touches[0].clientX);
      }
    };
    const onTouchEnd = () => setIsDragging(false);

    if (isDragging) {
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
      window.addEventListener('touchmove', onTouchMove);
      window.addEventListener('touchend', onTouchEnd);
    }
    return () => {
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
      window.removeEventListener('touchmove', onTouchMove);
      window.removeEventListener('touchend', onTouchEnd);
    };
  }, [isDragging, handleMove]);

  return (
    <div
      ref={containerRef}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
      className={`relative select-none overflow-hidden rounded-xl border border-slate-800 bg-slate-950 shadow-2xl cursor-ew-resize group ${aspectRatio} ${className}`}
    >
      {/* After image (Underneath / full width) */}
      <div className="absolute inset-0 w-full h-full">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={afterUrl}
          alt="After upscale"
          className="w-full h-full object-cover"
          draggable={false}
        />
        <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5 px-2.5 py-1 bg-emerald-950/80 border border-emerald-500/40 rounded-full text-emerald-300 text-[11px] font-semibold backdrop-blur-md shadow-lg pointer-events-none">
          <Sparkles className="w-3 h-3 text-emerald-400" />
          {afterLabel}
        </div>
      </div>

      {/* Before image (Clipped to left side) */}
      <div
        className="absolute inset-0 w-full h-full overflow-hidden pointer-events-none"
        style={{ clipPath: `inset(0 ${100 - sliderPosition}% 0 0)` }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={beforeUrl}
          alt="Before upscale"
          className="w-full h-full object-cover filter blur-[0.6px]"
          draggable={false}
        />
        <div className="absolute top-3 left-3 z-10 flex items-center gap-1.5 px-2.5 py-1 bg-slate-900/85 border border-slate-700/60 rounded-full text-slate-300 text-[11px] font-semibold backdrop-blur-md shadow-lg">
          <ImageIcon className="w-3 h-3 text-slate-400" />
          {beforeLabel}
        </div>
      </div>

      {/* Draggable Divider Line */}
      <div
        className="absolute top-0 bottom-0 z-20 pointer-events-none transition-transform"
        style={{ left: `${sliderPosition}%` }}
      >
        <div className="absolute top-0 bottom-0 -left-[1.5px] w-[3px] bg-gradient-to-b from-sky-400 via-white to-sky-400 shadow-[0_0_12px_rgba(56,189,248,0.8)]" />
        
        {/* Handle grip icon */}
        <div className="absolute top-1/2 -left-4 -translate-y-1/2 w-8 h-8 rounded-full bg-slate-900/90 border-2 border-white flex items-center justify-center text-white shadow-xl backdrop-blur-md group-hover:scale-110 transition-transform">
          <MoveHorizontal className="w-4 h-4 text-sky-400" />
        </div>
      </div>

      {/* Bottom percentage indicator */}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-10 px-2.5 py-0.5 bg-slate-900/70 border border-slate-800 rounded-full text-[10px] text-slate-400 font-mono backdrop-blur-sm pointer-events-none">
        Split: {Math.round(sliderPosition)}%
      </div>
    </div>
  );
}
