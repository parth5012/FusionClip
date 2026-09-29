'use client';
// PROTOTYPE route #125 — throwaway. Visit /precision-prototype?v=a|b|c

import React, { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import PrecisionPrototypePanel from '../../components/precision-prototype/PrecisionPrototypePanel';

function Inner() {
  const searchParams = useSearchParams();
  const initialVariant = (searchParams.get('v') || 'A').toUpperCase();
  return <PrecisionPrototypePanel initialVariant={initialVariant} />;
}

export default function PrecisionPrototypePage() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 px-4 py-6 max-w-7xl mx-auto">
      <h1 className="text-lg font-bold">Precision mode prototype (#125) — throwaway</h1>
      <p className="text-xs text-slate-400 mb-4">
        How Precision presents alongside Creative: mode toggle, Sharpness/Grain 0–100, scale to
        16x, engine selector. Flip A/B/C on the bottom bar, steal what you like, then we lock
        direction for #124.
      </p>
      <Suspense>
        <Inner />
      </Suspense>
    </div>
  );
}
