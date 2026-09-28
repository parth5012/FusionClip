'use client';

import React from 'react';
import { X, Check } from 'lucide-react';
import type { SkinSource } from './types';

interface SourceStripProps {
  sources: SkinSource[];
  selected: string[];
  focused: string | null;
  /** Click a thumb: select it if it is not selected yet, and always focus it. */
  onFocus: (path: string) => void;
  /** Explicit deselect control — selection and focus are separate intents (#113 decision 3). */
  onDeselect: (path: string) => void;
  disabled?: boolean;
}

/**
 * Multi-select portrait strip (C's contribution to the approved composite).
 *
 * A tap target must not change meaning on the second tap, so deselection lives
 * on its own `x` and a click only ever focuses/selects.
 */
export default function SourceStrip({
  sources,
  selected,
  focused,
  onFocus,
  onDeselect,
  disabled = false,
}: SourceStripProps) {
  if (sources.length === 0) {
    return (
      <div className="border-b border-slate-800 px-4 py-4 text-xs text-slate-500">
        No images in the catalog yet — upload a portrait to enhance it.
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2 overflow-x-auto border-b border-slate-800 px-4 py-3">
      {sources.map((source, index) => {
        const isSelected = selected.includes(source.path);
        const isFocus = focused === source.path;
        return (
          <div
            key={source.path}
            className={`relative shrink-0 overflow-hidden rounded-lg border-2 transition ${
              isFocus
                ? 'border-sky-400'
                : isSelected
                  ? 'border-amber-400'
                  : 'border-slate-800 opacity-60 hover:opacity-100'
            }`}
          >
            <button
              type="button"
              onClick={() => onFocus(source.path)}
              disabled={disabled}
              data-testid={`skin-source-${index}`}
              aria-pressed={isSelected}
              title={isSelected ? 'Show in the canvas' : 'Select and show in the canvas'}
              className="block"
            >
              {source.url ? (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img src={source.url} alt={source.name} className="h-14 w-14 object-cover" />
              ) : (
                <span className="flex h-14 w-14 items-center justify-center bg-slate-950 text-[9px] text-slate-500">
                  no preview
                </span>
              )}
            </button>

            {isSelected && (
              <>
                <span className="absolute left-0.5 top-0.5 grid h-3.5 w-3.5 place-items-center rounded-full bg-amber-400 text-slate-950">
                  <Check className="h-2.5 w-2.5" strokeWidth={4} />
                </span>
                <button
                  type="button"
                  onClick={() => onDeselect(source.path)}
                  disabled={disabled}
                  data-testid={`skin-remove-${index}`}
                  aria-label={`Remove ${source.name} from selection`}
                  title="Remove from selection"
                  className="absolute right-0.5 top-0.5 grid h-4 w-4 place-items-center rounded-full border border-slate-950/60 bg-slate-950/85 text-slate-300 transition hover:bg-rose-500 hover:text-white"
                >
                  <X className="h-2.5 w-2.5" strokeWidth={3} />
                </button>
              </>
            )}
          </div>
        );
      })}
      <span className="ml-1 shrink-0 font-mono text-[10px] text-slate-500">
        {selected.length} selected · click a thumb to focus
      </span>
    </div>
  );
}
