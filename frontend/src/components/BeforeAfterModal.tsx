'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

/**
 * Before/after comparison modal (map #58).
 *
 * Fullscreen overlay that lets the user drag a handle to reveal the original
 * vs. the upscaled result, with a 2x zoom magnifier tracking the divider.
 * Keyboard: arrow keys move the divider, Escape closes.
 */
interface BeforeAfterModalProps {
  beforeUrl: string;
  afterUrl: string;
  title?: string;
  beforeLabel?: string;
  afterLabel?: string;
  onClose: () => void;
}

export default function BeforeAfterModal({
  beforeUrl,
  afterUrl,
  title = 'Upscale Comparison',
  beforeLabel = 'Original',
  afterLabel = 'Upscaled',
  onClose,
}: BeforeAfterModalProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const beforeLayerRef = useRef<HTMLDivElement>(null);
  const dividerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const lensRef = useRef<HTMLDivElement>(null);
  const lensCanvasRef = useRef<HTMLCanvasElement>(null);

  // Preloaded source images for the zoom lens (avoids new Image() per move).
  const beforeImgRef = useRef<HTMLImageElement | null>(null);
  const afterImgRef = useRef<HTMLImageElement | null>(null);

  const [pos, setPos] = useState(50); // divider position in %
  const draggingRef = useRef(false);

  const clamp = (v: number) => Math.max(0, Math.min(100, v));

  const applyPos = useCallback((pct: number) => {
    const p = clamp(pct);
    setPos(p);
    if (beforeLayerRef.current) beforeLayerRef.current.style.width = `${p}%`;
    if (dividerRef.current) dividerRef.current.style.left = `${p}%`;
    if (handleRef.current) handleRef.current.style.left = `${p}%`;
  }, []);

  const clientXToPct = useCallback((clientX: number) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return 50;
    return ((clientX - rect.left) / rect.width) * 100;
  }, []);

  // Preload both images once for the zoom lens.
  useEffect(() => {
    const beforeImg = new Image();
    const afterImg = new Image();
    beforeImg.src = beforeUrl;
    afterImg.src = afterUrl;
    beforeImgRef.current = beforeImg;
    afterImgRef.current = afterImg;
  }, [beforeUrl, afterUrl]);

  // Zoom lens: magnify a 2x region centered on the pointer with the
  // before/after split baked in, matching the current divider position.
  const drawLens = useCallback(
    (clientX: number, clientY: number) => {
      const wrap = wrapRef.current;
      const canvas = lensCanvasRef.current;
      const lens = lensRef.current;
      if (!wrap || !canvas || !lens) return;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const beforeImg = beforeImgRef.current;
      const afterImg = afterImgRef.current;
      if (!beforeImg || !afterImg || beforeImg.naturalWidth === 0 || afterImg.naturalWidth === 0) return;

      const rect = wrap.getBoundingClientRect();
      const fx = clamp(((clientX - rect.left) / rect.width) * 100) / 100;
      const fy = clamp(((clientY - rect.top) / rect.height) * 100) / 100;

      const S = 420; // canvas backing
      const Z = 2.2;
      const viewW = S / Z;
      const viewH = S / Z;

      const srcW = beforeImg.naturalWidth;
      const srcH = beforeImg.naturalHeight;
      const sx = Math.min(srcW - viewW, Math.max(0, fx * srcW - viewW / 2));
      const sy = Math.min(srcH - viewH, Math.max(0, fy * srcH - viewH / 2));

      ctx.clearRect(0, 0, S, S);
      // after fills the whole lens
      ctx.drawImage(afterImg, sx, sy, viewW, viewH, 0, 0, S, S);
      // before clipped to the divider
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, S * (pos / 100), S);
      ctx.clip();
      ctx.drawImage(beforeImg, sx, sy, viewW, viewH, 0, 0, S, S);
      ctx.restore();

      // position lens above pointer
      lens.style.display = 'block';
      lens.style.left = `${fx * rect.width}px`;
      lens.style.top = `${Math.max(80, fy * rect.height - 48)}px`;
    },
    [beforeUrl, afterUrl, pos]
  );

  const hideLens = useCallback(() => {
    if (lensRef.current) lensRef.current.style.display = 'none';
  }, []);

  // Keyboard controls.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft') applyPos(pos - 4);
      if (e.key === 'ArrowRight') applyPos(pos + 4);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose, pos, applyPos]);

  // Prevent body scroll while open.
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/95 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-5xl bg-slate-900 border border-slate-700 rounded-xl overflow-hidden shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
          <h3 className="text-sm font-bold text-slate-100">{title}</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition"
            aria-label="Close comparison"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Comparison area */}
        <div
          ref={wrapRef}
          className="relative w-full select-none touch-none overflow-hidden"
          style={{ aspectRatio: '4/3' }}
          onMouseDown={(e) => {
            draggingRef.current = true;
            applyPos(clientXToPct(e.clientX));
            e.preventDefault();
          }}
          onMouseMove={(e) => {
            const pct = clientXToPct(e.clientX);
            const dx = Math.abs(pct - pos);
            if (draggingRef.current) {
              applyPos(pct);
              drawLens(e.clientX, e.clientY);
            } else if (dx < 10) {
              drawLens(e.clientX, e.clientY);
            } else {
              hideLens();
            }
          }}
          onMouseUp={() => {
            draggingRef.current = false;
            hideLens();
          }}
          onMouseLeave={() => {
            draggingRef.current = false;
            hideLens();
          }}
          onTouchStart={(e) => {
            draggingRef.current = true;
            applyPos(clientXToPct(e.touches[0].clientX));
          }}
          onTouchMove={(e) => {
            if (draggingRef.current) applyPos(clientXToPct(e.touches[0].clientX));
          }}
          onTouchEnd={() => {
            draggingRef.current = false;
            hideLens();
          }}
        >
          {/* After (full) */}
          <img
            src={afterUrl}
            alt="Upscaled"
            className="absolute inset-0 w-full h-full object-cover"
            draggable={false}
          />
          {/* Before (clipped) */}
          <div
            ref={beforeLayerRef}
            className="absolute inset-0 overflow-hidden"
            style={{ width: '50%' }}
          >
            <img
              src={beforeUrl}
              alt="Original"
              className="absolute inset-0 w-full h-full object-cover"
              draggable={false}
            />
          </div>

          {/* Labels */}
          <span className="absolute top-4 left-4 z-20 text-[11px] font-bold uppercase tracking-wider px-2.5 py-1 rounded bg-slate-950/80 text-rose-300 border border-rose-500/30">
            {beforeLabel}
          </span>
          <span className="absolute top-4 right-4 z-20 text-[11px] font-bold uppercase tracking-wider px-2.5 py-1 rounded bg-slate-950/80 text-emerald-300 border border-emerald-500/30">
            {afterLabel}
          </span>

          {/* Divider + handle */}
          <div
            ref={dividerRef}
            className="absolute top-0 bottom-0 w-0.5 bg-white z-10 cursor-ew-resize"
            style={{ left: '50%', boxShadow: '0 0 12px rgba(0,0,0,.6)' }}
          />
          <div
            ref={handleRef}
            className="absolute top-1/2 z-20 w-9 h-9 rounded-full bg-white text-slate-900 flex items-center justify-center text-xs font-bold shadow-lg -translate-x-1/2 -translate-y-1/2 cursor-ew-resize"
            style={{ left: '50%' }}
          >
            ↔
          </div>

          {/* Zoom lens */}
          <div
            ref={lensRef}
            className="absolute z-30 w-36 h-36 rounded-full overflow-hidden pointer-events-none hidden"
            style={{ border: '2px solid rgba(255,255,255,.9)', boxShadow: '0 4px 18px rgba(0,0,0,.55)', transform: 'translate(-50%,-50%)', background: '#0f172a' }}
          >
            <canvas ref={lensCanvasRef} width="420" height="420" className="w-full h-full block" />
            <div
              className="absolute inset-0 opacity-40"
              style={{
                background:
                  'linear-gradient(to right, rgba(255,255,255,.8) 0 1px, transparent 1px 100%), linear-gradient(to bottom, rgba(255,255,255,.8) 0 1px, transparent 1px 100%)',
                backgroundSize: '50% 50%',
                backgroundPosition: 'center',
                backgroundRepeat: 'no-repeat',
              }}
            />
          </div>
        </div>

        {/* Footer hint */}
        <div className="px-5 py-3 border-t border-slate-800 flex items-center justify-between text-[11px] text-slate-500">
          <span>Drag the handle or use ← / → keys to compare</span>
          <span className="font-mono">Esc to close</span>
        </div>
      </div>
    </div>
  );
}
