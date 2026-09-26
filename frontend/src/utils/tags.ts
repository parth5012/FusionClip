import type { MediaAsset, TagItem } from './api';

/**
 * Filter media assets by selected tags with AND semantics.
 * An asset must contain every selected tag (case-insensitive) to be included.
 * If selectedTags is empty, all assets are returned.
 */
export function filterAssetsByTags(
  assets: MediaAsset[],
  selectedTags: string[]
): MediaAsset[] {
  if (!selectedTags || selectedTags.length === 0) {
    return assets;
  }

  const normalizedSelected = selectedTags
    .map((t) => t.trim().toLowerCase())
    .filter(Boolean);

  if (normalizedSelected.length === 0) {
    return assets;
  }

  return assets.filter((asset) => {
    const assetTagNames = (asset.tags || []).map((t) => t.name.toLowerCase());
    return normalizedSelected.every((tag) => assetTagNames.includes(tag));
  });
}

/**
 * Extract and aggregate all unique tags across a list of media assets,
 * sorted by frequency descending, then alphabetically ascending.
 */
export function extractAllTags(
  assets: MediaAsset[]
): { name: string; count: number }[] {
  const counts: Record<string, number> = {};

  for (const asset of assets) {
    const seenOnAsset = new Set<string>();
    for (const tag of asset.tags || []) {
      const normalized = tag.name.trim().toLowerCase();
      if (!normalized || seenOnAsset.has(normalized)) continue;
      seenOnAsset.add(normalized);
      counts[normalized] = (counts[normalized] || 0) + 1;
    }
  }

  return Object.entries(counts)
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => {
      if (b.count !== a.count) {
        return b.count - a.count;
      }
      return a.name.localeCompare(b.name);
    });
}
