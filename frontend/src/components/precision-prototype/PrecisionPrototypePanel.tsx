'use client';
// PROTOTYPE #125 — throwaway panel wrapper. Three Precision-mode presentations,
// switchable via the floating bar and mirrored into ?v=a|b|c.

import React, { useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import VariantA from './VariantA';
import VariantB from './VariantB';
import VariantC from './VariantC';
import PrototypeSwitcher from '../upscale/PrototypeSwitcher';

const VARIANTS = [
  { id: 'A', name: 'Inline toggle' },
  { id: 'B', name: 'Canvas HUD' },
  { id: 'C', name: 'Rung grid' },
];

export default function PrecisionPrototypePanel({
  initialVariant = 'A',
}: {
  initialVariant?: string;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const valid = VARIANTS.some((v) => v.id === initialVariant) ? initialVariant : 'A';
  const [variant, setVariant] = useState(valid);

  const select = (next: string) => {
    setVariant(next);
    const params = new URLSearchParams(searchParams.toString());
    params.set('v', next.toLowerCase());
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  return (
    <div className="relative pb-24">
      <div className="mb-3 text-[11px] text-amber-300 bg-amber-950/40 border border-amber-800/60 rounded px-2 py-1">
        PROTOTYPE #125 — throwaway, read-only. Nothing here is wired to
        <span className="font-mono"> /api/upscale</span>. Payload block is the
        contract #124 will implement (decisions in #123).
      </div>

      {variant === 'A' && <VariantA />}
      {variant === 'B' && <VariantB />}
      {variant === 'C' && <VariantC />}

      <PrototypeSwitcher
        variants={VARIANTS}
        current={variant}
        onSelect={select}
        badge="Precision Prototype (#125)"
      />
    </div>
  );
}
