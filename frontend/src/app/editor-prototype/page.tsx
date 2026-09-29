'use client';
// PROTOTYPE route #120 — throwaway. Visit /editor-prototype?v=a|b|c

import React, { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import EditorPrototypePanel from '../../components/editor-prototype/EditorPrototypePanel';

function Inner() {
  const searchParams = useSearchParams();
  const initialVariant = (searchParams.get('v') || 'A').toUpperCase();
  return <EditorPrototypePanel initialVariant={initialVariant} />;
}

export default function EditorPrototypePage() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 px-4 py-6 max-w-7xl mx-auto">
      <h1 className="text-lg font-bold">Editor shell prototype (#120) — throwaway</h1>
      <p className="text-xs text-slate-400 mb-4">Variants A/B/C via bottom bar. React to layout, then we lock direction for #121 build.</p>
      <Suspense><Inner /></Suspense>
    </div>
  );
}
