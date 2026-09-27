// PROTOTYPE: Background Removal UI Prototype Types (Wayfinder #117 / Grilling #115)
// Throwaway prototype code for evaluating presentation variants.

import { StorageItem } from '../../utils/api';

export type BgRemoveTier = 'u2net' | 'birefnet';

export interface BgRemoveTierConfig {
  id: BgRemoveTier;
  label: string;
  badge: string;
  description: string;
  inferenceTime: string;
  vram: string;
  recommendedFor: string;
}

export const BG_REMOVE_TIERS: Record<BgRemoveTier, BgRemoveTierConfig> = {
  u2net: {
    id: 'u2net',
    label: 'Fast (U²-Net)',
    badge: 'Default',
    description: 'Fast edge-aware salient object segmentation. Optimal for portraits, products, and clean subjects.',
    inferenceTime: '~0.8s',
    vram: '1.2 GB',
    recommendedFor: 'E-commerce, portraits, clear contrast',
  },
  birefnet: {
    id: 'birefnet',
    label: 'Quality (BiRefNet)',
    badge: 'High Precision',
    description: 'Bilateral reference network for ultra-fine boundary refinement, loose hair, fur, and intricate transparency.',
    inferenceTime: '~2.4s',
    vram: '3.8 GB',
    recommendedFor: 'Fine hair, translucent fabrics, intricate silhouettes',
  },
};

export type BgRemoveStatus = 'idle' | 'processing' | 'preview' | 'accepted' | 'rejected';

export interface BgRemoveJobState {
  target: StorageItem;
  tier: BgRemoveTier;
  status: BgRemoveStatus;
  progress: number;
  stepMessage?: string;
  previewUrl?: string;
  derivativeName?: string;
}

export type InlineViewMode = 'original' | 'mask' | 'cutout';

export interface VariantProps {
  files: StorageItem[];
  onAddDerivative?: (derivative: StorageItem) => void;
}
