'use client';
// Editor canvas (#121) — production left pane following the approved Variant A
// layout (#120): canvas with before/after toggle plus the live recipe JSON.
// The preview is CSS-only; the server re-render is authoritative.

import React, { useState } from 'react';
import { canonicalRecipe, recipeToFilter } from '../../utils/editor';
import { useEditorStore } from '../../store/useEditorStore';

export default function EditorCanvas({
  src,
  alt,
}: {
  src: string;
  alt: string;
}) {
  const recipe = useEditorStore((s) => s.recipe);
  const [showOriginal, setShowOriginal] = useState(false);

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-bold text-slate-200">Preview</span>
        <button
          data-testid="editor-toggle-before-after"
          onClick={() => setShowOriginal((v) => !v)}
          className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
        >
          {showOriginal ? 'Before (original)' : 'After (preview)'} — toggle
        </button>
      </div>
      <div className="aspect-[16/10] rounded-lg overflow-hidden border border-slate-700 bg-slate-950 flex items-center justify-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          data-testid="editor-preview"
          src={src}
          alt={alt}
          className="w-full h-full object-cover"
          style={{
            filter: showOriginal ? 'none' : recipeToFilter(recipe),
            transform: `rotate(${showOriginal ? 0 : recipe.rotate}deg)`,
          }}
        />
      </div>
      <pre
        data-testid="editor-recipe-json"
        className="mt-2 text-[10px] font-mono text-slate-400 bg-slate-950/60 border border-slate-800 rounded p-2 overflow-auto"
      >
        {canonicalRecipe(recipe)}
      </pre>
    </div>
  );
}
