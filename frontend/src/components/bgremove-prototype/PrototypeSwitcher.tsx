'use client';

// PROTOTYPE: Floating Switcher Component (Wayfinder #117 / Grilling #115)
// Throwaway prototype switcher: fixed bottom-centre pill, updates ?variant= via Next router,
// cycles with arrow keys, gated to non-production.

import React, { useEffect, useCallback } from 'react';
import { useRouter, useSearchParams, usePathname } from 'next/navigation';
import { ChevronLeft, ChevronRight, Wand2 } from 'lucide-react';

export const PROTOTYPE_VARIANTS = [
  { id: 'panel', label: 'Variant A: Slide-over Panel', shortLabel: 'A: Panel' },
  { id: 'modal', label: 'Variant B: Modal Wizard', shortLabel: 'B: Modal' },
  { id: 'inline', label: 'Variant C: Inline Strip', shortLabel: 'C: Inline' },
] as const;

export type PrototypeVariantId = (typeof PROTOTYPE_VARIANTS)[number]['id'];

interface PrototypeSwitcherProps {
  currentVariant: PrototypeVariantId;
}

export default function PrototypeSwitcher({ currentVariant }: PrototypeSwitcherProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const handleSelect = useCallback(
    (variantId: string) => {
      const params = new URLSearchParams(searchParams ? searchParams.toString() : '');
      params.set('variant', variantId);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  const currentIndex = PROTOTYPE_VARIANTS.findIndex((v) => v.id === currentVariant);
  const safeIndex = currentIndex >= 0 ? currentIndex : 0;

  const handlePrev = useCallback(() => {
    const nextIdx = (safeIndex - 1 + PROTOTYPE_VARIANTS.length) % PROTOTYPE_VARIANTS.length;
    handleSelect(PROTOTYPE_VARIANTS[nextIdx].id);
  }, [safeIndex, handleSelect]);

  const handleNext = useCallback(() => {
    const nextIdx = (safeIndex + 1) % PROTOTYPE_VARIANTS.length;
    handleSelect(PROTOTYPE_VARIANTS[nextIdx].id);
  }, [safeIndex, handleSelect]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = (document.activeElement?.tagName || '').toLowerCase();
      if (
        activeTag === 'input' ||
        activeTag === 'textarea' ||
        (document.activeElement as HTMLElement)?.isContentEditable
      ) {
        return;
      }
      if (e.key === 'ArrowLeft') {
        e.preventDefault();
        handlePrev();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        handleNext();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handlePrev, handleNext]);

  // Gated: render only in non-production
  if (process.env.NODE_ENV === 'production') {
    return null;
  }

  return (
    <aside
      aria-label="Remove-background prototype switcher"
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-slate-900/95 border border-sky-500/60 shadow-2xl shadow-sky-950/80 px-4 py-2 rounded-full backdrop-blur-md text-xs select-none"
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase font-bold tracking-wider text-sky-400 bg-sky-950/80 border border-sky-800/80 px-2 py-0.5 rounded-full">
        <Wand2 className="w-3 h-3 text-sky-400" />
        <span>BG Remove #117</span>
      </div>

      <button
        onClick={handlePrev}
        className="p-1 rounded-full hover:bg-slate-800 text-slate-300 hover:text-white transition"
        title="Previous Variant (Left Arrow ←)"
        aria-label="Previous Variant"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>

      <div className="flex items-center gap-1">
        {PROTOTYPE_VARIANTS.map((v) => (
          <button
            key={v.id}
            onClick={() => handleSelect(v.id)}
            className={`px-3 py-1 rounded-full text-xs font-medium transition ${
              v.id === currentVariant
                ? 'bg-sky-500 text-slate-950 font-bold shadow-md'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/70'
            }`}
            title={`Switch to ${v.label}`}
          >
            {v.shortLabel}
          </button>
        ))}
      </div>

      <button
        onClick={handleNext}
        className="p-1 rounded-full hover:bg-slate-800 text-slate-300 hover:text-white transition"
        title="Next Variant (Right Arrow →)"
        aria-label="Next Variant"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </aside>
  );
}
