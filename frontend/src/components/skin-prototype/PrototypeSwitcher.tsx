'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * Floating variant switcher. Cycles with the arrow keys and the on-screen
 * arrows; writes to the `?skinVariant=` search param so a variant is
 * shareable and reload-stable. Hidden in production builds.
 */
import React, { useCallback, useEffect } from 'react';

const NAMES: Record<string, string> = {
  D: 'Composite (chosen)',
  A: 'Portrait Studio',
  B: 'Honest Knob',
  C: 'Batch Queue',
};

export default function PrototypeSwitcher({ current, onChange }: { current: string; onChange: (v: string) => void }) {
  const keys = ['D', 'A', 'B', 'C'];

  const cycle = useCallback(
    (dir: 1 | -1) => {
      const i = keys.indexOf(current);
      const next = keys[(i + dir + keys.length) % keys.length];
      onChange(next);
    },
    [current, onChange],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      const el = document.activeElement;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || (el as HTMLElement).isContentEditable)) {
        return; // never steal arrows from a focused control
      }
      e.preventDefault();
      cycle(e.key === 'ArrowRight' ? 1 : -1);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cycle]);

  if (process.env.NODE_ENV === 'production') return null;

  return (
    <div className="fixed bottom-5 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1 rounded-full bg-slate-950 ring-2 ring-amber-400/70 shadow-2xl px-2 py-1.5">
      <button
        onClick={() => cycle(-1)}
        aria-label="Previous variant"
        className="h-7 w-7 rounded-full text-amber-300 hover:bg-amber-400/20 text-sm leading-none"
      >
        ←
      </button>
      <span className="px-2 font-mono text-[11px] text-amber-200 whitespace-nowrap">
        {current} · {NAMES[current] ?? 'Skin Enhancer'}
      </span>
      <button
        onClick={() => cycle(1)}
        aria-label="Next variant"
        className="h-7 w-7 rounded-full text-amber-300 hover:bg-amber-400/20 text-sm leading-none"
      >
        →
      </button>
    </div>
  );
}
