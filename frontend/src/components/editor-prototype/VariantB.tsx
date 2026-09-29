'use client';
// PROTOTYPE (#120 Variant B) — throwaway Bottom-drawer grouped controls.

import React, { useState } from 'react';
import { EditorRecipe, SLIDERS, recipeToFilter } from './types';

export default function VariantB({
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
  const [tab, setTab] = useState<'light' | 'color' | 'grain-crop'>('light');
  const lightKeys = ['exposure', 'brightness', 'contrast', 'highlights', 'shadows'] as const;
  const colorKeys = ['tint'] as const;
  return (
    <div className="space-y-3">
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4">
        <div className="text-xs font-bold text-slate-200 mb-2">B: Canvas center + bottom drawer</div>
        <div className="aspect-[16/8] rounded-lg overflow-hidden border border-slate-700 bg-slate-950">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="https://picsum.photos/seed/fusionclip-editor/1280/640"
            alt="prototype source"
            className="w-full h-full object-cover"
            style={{ filter: recipe.showBeforeAfter ? 'none' : recipeToFilter(recipe), transform: `rotate(${recipe.rotate}deg)` }}
          />
        </div>
        <div className="flex gap-2 mt-2">
          <button onClick={() => setRecipe({ ...recipe, showBeforeAfter: !recipe.showBeforeAfter })} className="text-[11px] px-2 py-1 bg-slate-800 rounded">before/after</button>
          <button onClick={onApply} className="text-[11px] px-3 py-1 bg-sky-600 rounded font-bold">Apply</button>
          <button onClick={onCancel} className="text-[11px] px-3 py-1 bg-slate-800 rounded">Cancel</button>
          <button onClick={onExport} className="text-[11px] px-3 py-1 bg-emerald-700 rounded">Export</button>
        </div>
      </div>
      <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-3">
        <div className="flex gap-1 mb-2">
          {(['light', 'color', 'grain-crop'] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`text-[11px] px-2 py-1 rounded ${tab === t ? 'bg-sky-600 text-white' : 'bg-slate-800 text-slate-300'}`}>{t}</button>
          ))}
        </div>
        {tab === 'light' && lightKeys.map((k) => {
          const meta = SLIDERS.find((s) => s.key === k)!;
          return (
            <div key={k}>
              <div className="flex justify-between text-xs"><span>{meta.label}</span><span className="font-mono text-sky-400">{recipe[k]}</span></div>
              <input type="range" min={meta.min} max={meta.max} value={recipe[k]} onChange={(e) => setRecipe({ ...recipe, [k]: Number(e.target.value) })} className="w-full accent-sky-500" />
            </div>
          );
        })}
        {tab === 'color' && colorKeys.map((k) => {
          const meta = SLIDERS.find((s) => s.key === k)!;
          return (
            <div key={k}>
              <div className="flex justify-between text-xs"><span>{meta.label}</span><span className="font-mono text-sky-400">{recipe[k]}</span></div>
              <input type="range" min={meta.min} max={meta.max} value={recipe[k]} onChange={(e) => setRecipe({ ...recipe, [k]: Number(e.target.value) })} className="w-full accent-indigo-500" />
            </div>
          );
        })}
        {tab === 'grain-crop' && (
          <div className="space-y-2">
            <div><div className="flex justify-between text-xs"><span>Grain</span><span className="font-mono text-sky-400">{recipe.grain}</span></div>
            <input type="range" min={0} max={100} value={recipe.grain} onChange={(e) => setRecipe({ ...recipe, grain: Number(e.target.value) })} className="w-full accent-amber-500" /></div>
            <div className="flex gap-2 items-center text-[11px]">
              <button onClick={() => setRecipe({ ...recipe, rotate: 0 })} className="px-2 py-1 bg-slate-800 rounded">reset rot ({recipe.rotate}°)</button>
              <input type="range" min={-45} max={45} value={recipe.rotate} onChange={(e) => setRecipe({ ...recipe, rotate: Number(e.target.value) })} className="flex-1 accent-slate-300" />
              <select value={recipe.cropAspect} onChange={(e) => setRecipe({ ...recipe, cropAspect: e.target.value as EditorRecipe['cropAspect'] })} className="bg-slate-950 border border-slate-700 rounded px-1">
                <option value="free">free</option><option value="1:1">1:1</option><option value="4:3">4:3</option><option value="16:9">16:9</option>
              </select>
            </div>
          </div>
        )}
        <pre className="mt-2 text-[10px] font-mono text-slate-500">{JSON.stringify(recipe)}</pre>
      </div>
    </div>
  );
}
