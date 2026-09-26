/**
 * Utility functions for batch asset selection and export packaging.
 */

import type { MediaAsset } from './api';

export interface ExportAssetCountResult {
  selectedCount: number;
  derivativesCount: number;
  totalFiles: number;
}

/**
 * Compute the total number of files to be exported given selected asset IDs.
 * When includeDerivatives is true, includes all upscaled_assets linked to selected assets.
 */
export function computeExportAssetCount(
  assets: MediaAsset[],
  selectedIds: Set<number>,
  includeDerivatives: boolean = true
): ExportAssetCountResult {
  let selectedCount = 0;
  let derivativesCount = 0;

  for (const asset of assets) {
    if (selectedIds.has(asset.id)) {
      selectedCount += 1;
      if (includeDerivatives && asset.upscaled_assets) {
        derivativesCount += asset.upscaled_assets.length;
      }
    }
  }

  return {
    selectedCount,
    derivativesCount,
    totalFiles: selectedCount + derivativesCount,
  };
}

/**
 * Format a human-readable summary label of what will be exported.
 */
export function formatExportCountLabel(
  selectedCount: number,
  derivativesCount: number,
  includeDerivatives: boolean = true
): string {
  const assetWord = selectedCount === 1 ? '1 asset' : `${selectedCount} assets`;
  if (!includeDerivatives || derivativesCount === 0) {
    return assetWord;
  }
  const derivWord = derivativesCount === 1 ? '1 derivative' : `${derivativesCount} derivatives`;
  return `${assetWord} + ${derivWord}`;
}

/**
 * Toggle an item in a Set (returns a new Set).
 */
export function toggleItemSelection<T>(currentSet: Set<T>, item: T): Set<T> {
  const next = new Set(currentSet);
  if (next.has(item)) {
    next.delete(item);
  } else {
    next.add(item);
  }
  return next;
}

/**
 * Select all or deselect all items. If all are currently selected, clears the set;
 * otherwise selects all items.
 */
export function toggleSelectAllItems<T>(currentSet: Set<T>, allItems: T[]): Set<T> {
  if (allItems.length > 0 && allItems.every((item) => currentSet.has(item))) {
    return new Set<T>();
  }
  return new Set<T>(allItems);
}

/**
 * Check if all items in the array are present in the set.
 */
export function isAllItemsSelected<T>(currentSet: Set<T>, allItems: T[]): boolean {
  return allItems.length > 0 && allItems.every((item) => currentSet.has(item));
}
