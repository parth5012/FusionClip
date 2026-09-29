'use client';
// PROTOTYPE (#120 Variant A) — throwaway Right-panel Magnific-like.

import React from 'react';
import { EditorRecipe, SLIDERS, recipeToFilter } from './types';

export default function VariantA({
  recipe,
  setRecipe,
  onApply,
  onCancel,
  onExport,
}: {
  recipe: EditorRecipe;
  setRecipe: (r: EditorRecipe) => void;
  onApply: () => void;
  onCancel: () => void;
  onExport: () => void;
}) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-8 bg-slate-900/70 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-bold text-slate-200">A: Canvas left + sliders right</span>
          <button
            onClick={() => setRecipe({ ...recipe, showBeforeAfter: !recipe.showBeforeAfter })}
            className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200"
          >
            {recipe.showBeforeAfter ? 'Before (original)' : 'After (filtered)'} — toggle
          </button>
        </div>
        <div className="aspect-[16/10] rounded-lg overflow-hidden border border-slate-700 bg-slate-950 flex items-center justify-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://picsum.photos/seed/fusionclip-editor/1280/800"
            alt="prototype source"
            className="w-full h-full object-cover"
            style={{
              filter: recipe.showBeforeAfter ? 'none' : recipeToFilter(recipe),
              // CodeRabbit #141: Before mode shows the true original — no rotation.
              transform: `rotate(${recipe.showBeforeAfter ? 0 : recipe.rotate}deg)`,
            }}
          />
        </div>
        <pre className="mt-2 text-[10px] font-mono text-slate-400 bg-slate-950/60 border border-slate-800 rounded p-2 overflow-auto">
          {JSON.stringify(recipe, null, 1)}
        </pre>
      </div>
      <div className="lg:col-span-4 bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3">
        {SLIDERS.map((s) => (
          <div key={s.key}>
            <div className="flex justify-between text-xs">
              <span className="text-slate-300">{s.label}</span>
              <span className="font-mono text-sky-400">{recipe[s.key] as number}</span>
            </div>
            <input
              type="range"
              min={s.min}
              max={s.max}
              value={recipe[s.key] as number}
              onChange={(e) => setRecipe({ ...recipe, [s.key]: Number(e.target.value) })}
              className="w-full accent-sky-500"
            />
          </div>
        ))}
        <div className="flex gap-2 pt-1">
          {/* CodeRabbit #141: clamp to the declared -45..45 recipe range. */}
          <button onClick={() => setRecipe({ ...recipe, rotate: Math.max(-45, recipe.rotate - 5) })} className="text-[11px] px-2 py-1 bg-slate-800 rounded">⟲ -5°</button>
          <button onClick={() => setRecipe({ ...recipe, rotate: Math.min(45, recipe.rotate + 5) })} className="text-[11px] px-2 py-1 bg-slate-800 rounded">⟳ +5°</button>
          <select
            value={recipe.cropAspect}
            onChange={(e) => setRecipe({ ...recipe, cropAspect: e.target.value as EditorRecipe['cropAspect'] })}
            className="text-[11px] bg-slate-950 border border-slate-700 rounded px-1"
          >
            <option value="free">crop: free</option>
            <option value="1:1">crop: 1:1</option>
            <option value="4:3">crop: 4:3</option>
            <option value="16:9">crop: 16:9</option>
          </select>
        </div>
        <div className="flex gap-2 pt-2">
          <button onClick={onApply} className="flex-1 text-xs font-bold bg-sky-600 hover:bg-sky-500 text-white rounded py-2">Apply</button>
          <button onClick={onCancel} className="text-xs px-3 bg-slate-800 rounded py-2">Cancel</button>
          <button onClick={onExport} className="text-xs px-3 bg-emerald-700 rounded py-2">Export</button>
        </div>
      </div>
    </div>
  );
}
