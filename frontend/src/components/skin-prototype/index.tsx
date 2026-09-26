'use client';

/**
 * PROTOTYPE — map #73 ticket #113. Throwaway: nothing here ships.
 *
 * Host. Mounted on the existing Library tab (sub-shape A of the prototype
 * skill) so the variants are judged against the real FileManager rather than
 * in a vacuum. Variants switch on `?skinVariant=A|B|C`.
 */
import React, { Suspense, useCallback } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import PrototypeSwitcher from './PrototypeSwitcher';
import VariantA from './VariantA';
import VariantB from './VariantB';
import VariantC from './VariantC';
import VariantD from './VariantD';

export default function SkinPrototypeHost() {
  const router = useRouter();
  const params = useSearchParams();
  const variant = (params.get('skinVariant') ?? 'D').toUpperCase();

  const setVariant = useCallback(
    (v: string) => {
      const next = new URLSearchParams(params.toString());
      next.set('skinVariant', v);
      router.replace(`?${next.toString()}`, { scroll: false });
    },
    [params, router],
  );

  return (
    <div className="mt-6">
      <div className="mb-2 flex items-center gap-2">
        <span className="rounded bg-amber-400/15 px-1.5 py-0.5 font-mono text-[10px] text-amber-300 ring-1 ring-amber-400/40">
          PROTOTYPE
        </span>
        <span className="text-[11px] text-slate-500">
          map #73 / ticket #113 — three layouts for the Skin Enhancer panel. ← → to switch. Nothing here is wired to
          the backend.
        </span>
      </div>

      <Suspense fallback={<div className="text-xs text-slate-600">loading variant…</div>}>
        {variant === 'A' && <VariantA />}
        {variant === 'B' && <VariantB />}
        {variant === 'C' && <VariantC />}
        {variant === 'D' && <VariantD />}
        {variant !== 'A' && variant !== 'B' && variant !== 'C' && variant !== 'D' && <VariantD />}
      </Suspense>

      <PrototypeSwitcher current={variant} onChange={setVariant} />
    </div>
  );
}
