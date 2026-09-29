'use client';
// PROTOTYPE (#120 Variant C) — throwaway Stepped Adjust→Crop→Export.

import React, { useState } from 'react';
import { EditorRecipe, SLIDERS, recipeToFilter } from './types';

export default function VariantC({
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
  const [step, setStep] = useState<'adjust' | 'crop' | 'export'>('adjust');
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <div className="lg:col-span-3 bg-slate-900/70 border border-slate-800 rounded-xl p-3 space-y-1">
        <div className="text-xs font-bold text-slate-200 mb-1">C: Stepped</div>
        {(['adjust', 'crop', 'export'] as const).map((s) => (
          <button key={s} onClick={() => setStep(s)} className={`w-full text-left text-xs px-2 py-2 rounded ${step === s ? 'bg-sky-600 text-white font-bold' : 'bg-slate-800/60 text-slate-300'}`}>{s}</button>
        ))}
        <div className="pt-2 space-y-1">
          <button onClick={onApply} className="w-full text-xs bg-sky-600 rounded py-1.5 font-bold">Apply</button>
          <button onClick={onCancel} className="w-full text-xs bg-slate-800 rounded py-1.5">Cancel</button>
          <button onClick={onExport} className="w-full text-xs bg-emerald-700 rounded py-1.5">Export</button>
        </div>
      </div>
      <div className="lg:col-span-9 bg-slate-900/70 border border-slate-800 rounded-xl p-4">
        <div className="aspect-[16/8] rounded border border-slate-700 overflow-hidden bg-slate-950 mb-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="https://picsum.photos/seed/fusionclip-editor/1280/640" alt="src" className="w-full h-full object-cover" style={{ filter: recipe.showBeforeAfter ? 'none' : recipeToFilter(recipe), transform: `rotate(${recipe.rotate}deg)` }} />
        </div>
        <button onClick={() => setRecipe({ ...recipe, showBeforeAfter: !recipe.showBeforeAfter })} className="text-[11px] px-2 py-1 bg-slate-800 rounded mb-2">toggle before/after</button>
        {step === 'adjust' && SLIDERS.map((s) => (
          <div key={s.key}><div className="flex justify-between text-xs"><span>{s.label}</span><span className="font-mono text-sky-400">{recipe[s.key] as number}</span></div>
          <input type="range" min={s.min} max={s.max} value={recipe[s.key] as number} onChange={(e) => setRecipe({ ...recipe, [s.key]: Number(e.target.value) })} className="w-full accent-sky-500" /></div>
        ))}
        {step === 'crop' && (
          <div className="flex gap-2 items-center text-xs">
            <span>rotate {recipe.rotate}°</span>
            <input type="range" min={-45} max={45} value={recipe.rotate} onChange={(e) => setRecipe({ ...recipe, rotate: Number(e.target.value) })} className="flex-1" />
            <select value={recipe.cropAspect} onChange={(e) => setRecipe({ ...recipe, cropAspect: e.target.value as EditorRecipe['cropAspect'] })} className="bg-slate-950 border border-slate-700 rounded px-1">
              <option value="free">free</option><option value="1:1">1:1</option><option value="4:3">4:3</option><option value="16:9">16:9</option>
            </select>
          </div>
        )}
        {step === 'export' && <pre className="text-[11px] font-mono text-slate-300 bg-slate-950 border border-slate-800 rounded p-2">{JSON.stringify(recipe, null, 2)}</pre>}
      </div>
    </div>
  );
}
