'use client';

import React, { useRef, useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { SkinItemState, SkinSource } from './types';

interface CompareCanvasProps {
  source: SkinSource | null;
  item?: SkinItemState;
  /** Progress line for the focused item (engine + stated per-image budget while running). */
  statusText: string;
}

/**
 * A's contribution to the approved composite: the before/after comparison is
 * the hero. The split only means something once a run produced an `after`; until
 * then the canvas shows the source and says so rather than faking a result.
 */
export default function CompareCanvas({ source, item, statusText }: CompareCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [split, setSplit] = useState(50);
  const [dragging, setDragging] = useState(false);

  if (!source) {
    return (
      <div
        data-testid="skin-canvas"
        className="flex aspect-[4/5] max-h-[27rem] w-full items-center justify-center bg-slate-950 text-xs text-slate-500"
      >
        Select a portrait to preview it here.
      </div>
    );
  }

  const hasResult = item?.status === 'completed' && Boolean(item.resultUrl);
  const beforeUrl = source.url ?? '';
  const afterUrl = hasResult ? item!.resultUrl! : '';

  const moveTo = (clientX: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0) return;
    const pct = ((clientX - rect.left) / rect.width) * 100;
    setSplit(Math.max(0, Math.min(100, pct)));
  };

  const showProgress = item?.status === 'running' || item?.status === 'queued';
  const clip = Math.max(split, 0.5);

  return (
    <div className="border-b border-slate-800 lg:border-b-0 lg:border-r">
      <div
        ref={containerRef}
        data-testid="skin-canvas"
        className="relative aspect-[4/5] max-h-[27rem] w-full select-none overflow-hidden bg-slate-950"
        onPointerDown={(e) => {
          if (!hasResult) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          setDragging(true);
          moveTo(e.clientX);
        }}
        onPointerMove={(e) => {
          if (dragging) moveTo(e.clientX);
        }}
        onPointerUp={() => setDragging(false)}
        onPointerCancel={() => setDragging(false)}
      >
        {beforeUrl && (
          /* eslint-disable-next-line @next/next/no-img-element */
          <img
            src={hasResult ? afterUrl : beforeUrl}
            alt={hasResult ? `${source.name} enhanced` : source.name}
            className="absolute inset-0 h-full w-full object-cover"
            draggable={false}
          />
        )}

        {hasResult && beforeUrl && (
          <div
            className="absolute inset-y-0 left-0 overflow-hidden"
            style={{ width: `${clip}%` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={beforeUrl}
              alt={`${source.name} before`}
              className="h-full object-cover"
              style={{ width: `${(100 / clip) * 100}%` }}
              draggable={false}
            />
          </div>
        )}

        {hasResult && (
          <div
            role="slider"
            tabIndex={0}
            aria-label="Before after split"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(split)}
            data-testid="skin-split"
            onKeyDown={(e) => {
              if (e.key === 'ArrowLeft') setSplit((v) => Math.max(0, v - 4));
              if (e.key === 'ArrowRight') setSplit((v) => Math.min(100, v + 4));
            }}
            className="absolute inset-y-0 z-10 w-0.5 cursor-ew-resize bg-amber-300/90"
            style={{ left: `${split}%` }}
          >
            <span className="absolute top-1/2 grid h-7 w-7 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full bg-amber-300 text-[10px] font-bold text-slate-900">
              ↔
            </span>
          </div>
        )}

        <span className="absolute left-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-300">
          before
        </span>
        <span
          className={`absolute right-2 top-2 rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] ${
            hasResult ? 'text-emerald-300' : 'text-slate-400'
          }`}
        >
          {hasResult ? 'after' : 'preview'}
        </span>
        <span className="absolute left-2 top-8 max-w-[70%] truncate rounded bg-slate-950/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
          {source.name}
        </span>

        {showProgress && (
          <div className="absolute inset-x-0 bottom-0 bg-slate-950/85 px-3 py-2">
            <p className="flex items-center gap-1.5 font-mono text-[10px] text-amber-200">
              <Loader2 className="h-3 w-3 animate-spin" />
              {statusText}
            </p>
          </div>
        )}

        {item?.status === 'completed' && (
          <span className="absolute bottom-2 left-2 rounded bg-slate-950/85 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
            {`Enhanced ${item.faces ?? 0} ${(item.faces ?? 0) === 1 ? 'face' : 'faces'}`}
          </span>
        )}
      </div>
    </div>
  );
}
