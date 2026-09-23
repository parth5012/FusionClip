'use client';

import React, { useState, useEffect } from 'react';
import VariantA from './generation/VariantA';
import VariantB from './generation/VariantB';
import VariantC from './generation/VariantC';
import PrototypeSwitcher from './generation/PrototypeSwitcher';

export default function GenerationPanel() {
  const [variant, setVariant] = useState<string>('A');

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const v = params.get('variant');
      if (v && ['A', 'B', 'C'].includes(v.toUpperCase())) {
        setVariant(v.toUpperCase());
      }
    }
  }, []);

  const handleSelectVariant = (newVariant: string) => {
    setVariant(newVariant);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.set('variant', newVariant);
      window.history.replaceState({}, '', url.toString());
    }
  };

  const variants = [
    { id: 'A', name: 'Tabbed Studio' },
    { id: 'B', name: 'Command Console' },
    { id: 'C', name: 'Multi-Pane Workspace' },
  ];

  return (
    <div className="relative pb-24">
      {variant === 'A' && <VariantA />}
      {variant === 'B' && <VariantB />}
      {variant === 'C' && <VariantC />}

      <PrototypeSwitcher
        variants={variants}
        current={variant}
        onSelect={handleSelectVariant}
      />
    </div>
  );
}
