'use client';

import React, { useEffect } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PrototypeSwitcherProps {
  variants: { id: string; name: string }[];
  current: string;
  onSelect: (variant: string) => void;
}

export default function PrototypeSwitcher({
  variants,
  current,
  onSelect,
}: PrototypeSwitcherProps) {
  const currentIndex = variants.findIndex((v) => v.id === current);
  const currentVariant = variants[currentIndex] || variants[0];

  const prev = () => {
    const nextIdx = (currentIndex - 1 + variants.length) % variants.length;
    onSelect(variants[nextIdx].id);
  };

  const next = () => {
    const nextIdx = (currentIndex + 1) % variants.length;
    onSelect(variants[nextIdx].id);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeTag = (document.activeElement?.tagName || '').toLowerCase();
      if (activeTag === 'input' || activeTag === 'textarea' || (document.activeElement as HTMLElement)?.isContentEditable) {
        return;
      }
      if (e.key === 'ArrowLeft') {
        prev();
      } else if (e.key === 'ArrowRight') {
        next();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [currentIndex, variants]);

  return (
    <aside aria-label="Prototype switcher" className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-slate-900/95 border border-sky-500/50 shadow-2xl shadow-sky-950/50 px-4 py-2 rounded-full backdrop-blur-md text-xs">
      <span className="text-[10px] uppercase font-bold tracking-wider text-sky-400 bg-sky-950/60 border border-sky-800/60 px-2 py-0.5 rounded-full">
        UI Prototype
      </span>
      <button
        onClick={prev}
        className="p-1 rounded-full hover:bg-slate-800 text-slate-300 hover:text-white transition"
        title="Previous Variant (Left Arrow)"
      >
        <ChevronLeft className="w-4 h-4" />
      </button>
      <div className="flex items-center gap-1.5 px-2">
        {variants.map((v) => (
          <button
            key={v.id}
            onClick={() => onSelect(v.id)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition ${
              v.id === current
                ? 'bg-sky-500 text-slate-950 font-bold shadow-sm'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
            }`}
          >
            {v.id}: {v.name}
          </button>
        ))}
      </div>
      <button
        onClick={next}
        className="p-1 rounded-full hover:bg-slate-800 text-slate-300 hover:text-white transition"
        title="Next Variant (Right Arrow)"
      >
        <ChevronRight className="w-4 h-4" />
      </button>
    </aside>
  );
}
