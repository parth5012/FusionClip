'use client';

import React, { useState } from 'react';
import VariantA from './upscale/VariantA';
import VariantB from './upscale/VariantB';
import VariantC from './upscale/VariantC';
import PrototypeSwitcher from './upscale/PrototypeSwitcher';

export default function UpscalePanel() {
  const [currentVariant, setCurrentVariant] = useState('A');

  const variants = [
    { id: 'A', name: 'Studio Workspace' },
    { id: 'B', name: 'Canvas HUD' },
    { id: 'C', name: 'Batch-First Grid' },
  ];

  return (
    <div className="relative pb-20">
      {currentVariant === 'A' && <VariantA />}
      {currentVariant === 'B' && <VariantB />}
      {currentVariant === 'C' && <VariantC />}

      {/* Interactive Prototype Switcher */}
      <PrototypeSwitcher
        variants={variants}
        current={currentVariant}
        onSelect={setCurrentVariant}
      />
    </div>
  );
}
