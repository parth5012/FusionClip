'use client';
// PROTOTYPE (#120) — throwaway panel wrapper with switcher + shared recipe state.

import React, { useState } from 'react';
import VariantA from './VariantA';
import VariantB from './VariantB';
import VariantC from './VariantC';
import PrototypeSwitcher from '../upscale/PrototypeSwitcher';
import { DEFAULT_RECIPE, EditorRecipe } from './types';

export default function EditorPrototypePanel() {
  const [variant, setVariant] = useState('A');
  const [recipe, setRecipe] = useState<EditorRecipe>(DEFAULT_RECIPE);
  const [log, setLog] = useState<string[]>([]);

  const variants = [
    { id: 'A', name: 'Right panel' },
    { id: 'B', name: 'Bottom drawer' },
    { id: 'C', name: 'Stepped' },
  ];

  return (
    <div className="relative pb-20">
      <div className="mb-3 text-[11px] text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded px-2 py-1">
        PROTOTYPE #120 — throwaway, CSS preview only. Authoritative render is Celery/ffmpeg (#118). No persistence.
      </div>
      {variant === 'A' && <VariantA recipe={recipe} setRecipe={setRecipe} onApply={() => setLog((l) => [`apply ${JSON.stringify(recipe)}`, ...l])} onCancel={() => { setRecipe(DEFAULT_RECIPE); setLog((l) => ['cancel→reset', ...l]); }} onExport={() => setLog((l) => [`export recipe v1 ${Date.now()}`, ...l])} />}
      {variant === 'B' && <VariantB recipe={recipe} setRecipe={setRecipe} onApply={() => setLog((l) => [`apply ${JSON.stringify(recipe)}`, ...l])} onCancel={() => { setRecipe(DEFAULT_RECIPE); setLog((l) => ['cancel→reset', ...l]); }} onExport={() => setLog((l) => [`export recipe v1 ${Date.now()}`, ...l])} />}
      {variant === 'C' && <VariantC recipe={recipe} setRecipe={setRecipe} onApply={() => setLog((l) => [`apply ${JSON.stringify(recipe)}`, ...l])} onCancel={() => { setRecipe(DEFAULT_RECIPE); setLog((l) => ['cancel→reset', ...l]); }} onExport={() => setLog((l) => [`export recipe v1 ${Date.now()}`, ...l])} />}
      {log.length > 0 && (
        <div className="mt-3 text-[11px] font-mono text-slate-400 space-y-0.5">
          {log.slice(0, 5).map((l, i) => <div key={i}>• {l}</div>)}
        </div>
      )}
      <PrototypeSwitcher variants={variants} current={variant} onSelect={setVariant} />
    </div>
  );
}
