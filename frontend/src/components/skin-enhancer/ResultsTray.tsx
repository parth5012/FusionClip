'use client';

import React from 'react';
import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react';
import { skinItemStatusText, type SkinMode } from '../../utils/skin';
import type { SkinItemState, SkinSource } from './types';

interface ResultsTrayProps {
  items: Array<{ source: SkinSource; item?: SkinItemState }>;
  focused: string | null;
  onFocus: (path: string) => void;
  mode: SkinMode;
}

/**
 * C's contribution: one row per selected source with its own progress.
 *
 * Rows move focus; the canvas follows (#113 decision 1). Degraded runs render
 * the amber card the rest of the app uses for an honest refusal, never a
 * success state.
 */
export default function ResultsTray({ items, focused, onFocus, mode }: ResultsTrayProps) {
  if (items.length === 0) return null;

  return (
    <div className="space-y-1.5 p-3" data-testid="skin-results">
      {items.map(({ source, item }, index) => {
        const status = item?.status ?? 'queued';
        return (
          <div key={source.path} data-testid={`skin-result-${index}`}>
            <button
              type="button"
              onClick={() => onFocus(source.path)}
              aria-label={`Show ${source.name} in the canvas`}
              className={`flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-1.5 text-left transition ${
                focused === source.path
                  ? 'border-sky-500/60 bg-sky-500/5'
                  : 'border-slate-800 hover:border-slate-700'
              }`}
            >
              {status === 'completed' && item?.resultUrl ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img src={item.resultUrl} alt={`${source.name} result`} className="h-7 w-7 rounded object-cover" />
              ) : source.url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={source.url}
                  alt={`${source.name} preview`}
                  className={`h-7 w-7 rounded object-cover ${status === 'running' ? '' : 'opacity-50'}`}
                />
              ) : (
                <span className="h-7 w-7 rounded bg-slate-950" />
              )}

              <span className="min-w-0 flex-1 truncate text-[11px] text-slate-300">
                {source.name}
              </span>

              <span
                role="status"
                className="flex shrink-0 items-center gap-1.5 font-mono text-[10px]"
              >
                {status === 'completed' && (
                  <span className="inline-flex items-center gap-1 text-emerald-300">
                    <CheckCircle2 className="h-3 w-3" /> {skinItemStatusText({ status, faces: item?.faces }, mode)}
                  </span>
                )}
                {(status === 'queued' || status === 'running') && (
                  <span className={status === 'running' ? 'text-amber-300' : 'text-slate-500'}>
                    {skinItemStatusText({ status }, mode)}
                  </span>
                )}
                {status === 'failed' && (
                  <span className="inline-flex items-center gap-1 text-rose-300">
                    <XCircle className="h-3 w-3" /> failed
                  </span>
                )}
                {status === 'degraded' && (
                  <span className="inline-flex items-center gap-1 text-amber-300">
                    <AlertTriangle className="h-3 w-3" /> degraded
                  </span>
                )}
              </span>
            </button>

            {status === 'degraded' && item?.degraded && (
              <div className="mt-1 ml-9 rounded-md border border-amber-900/60 bg-amber-950/30 px-3 py-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-bold text-slate-200">Local pipeline unavailable</span>
                  <span className="font-mono text-[10px] text-amber-400">{item.degraded.reason}</span>
                </div>
                <p className="mt-0.5 text-[11px] text-slate-400">{item.degraded.message}</p>
              </div>
            )}

            {status === 'failed' && item?.failure && (
              <div className="mt-1 ml-9 rounded-md border border-rose-900/50 bg-rose-950/30 px-3 py-2">
                <div className="flex items-center justify-between gap-2 text-xs">
                  <span className="font-bold text-slate-200">Refused</span>
                  {item.failure.slug && (
                    <span className="font-mono text-[10px] text-rose-300">{item.failure.slug}</span>
                  )}
                </div>
                <p className="mt-0.5 text-[11px] text-slate-400">{item.failure.human}</p>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
