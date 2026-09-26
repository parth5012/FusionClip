import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  computeExportAssetCount,
  toggleItemSelection,
  toggleSelectAllItems,
  isAllItemsSelected,
  formatExportCountLabel,
} from './export';
import type { MediaAsset } from './api';

describe('export utilities', () => {
  const dummyAssets: MediaAsset[] = [
    {
      id: 1,
      title: 'Original Photo',
      file_path: 'photo.jpg',
      file_size: 1000,
      content_type: 'image/jpeg',
      duration: 0,
      url: 'http://test/photo.jpg',
      source_path: null,
      source_url: null,
      upscaled_assets: [
        {
          id: 101,
          title: 'Upscaled Photo 4x',
          file_path: 'upscaled/photo_4x.jpg',
          url: 'http://test/photo_4x.jpg',
        },
      ],
      tags: [],
      created_at: null,
    },
    {
      id: 2,
      title: 'Video Clip',
      file_path: 'clip.mp4',
      file_size: 5000,
      content_type: 'video/mp4',
      duration: 10,
      url: 'http://test/clip.mp4',
      source_path: null,
      source_url: null,
      upscaled_assets: [],
      tags: [],
      created_at: null,
    },
    {
      id: 3,
      title: 'Music Track',
      file_path: 'music.mp3',
      file_size: 2000,
      content_type: 'audio/mpeg',
      duration: 60,
      url: 'http://test/music.mp3',
      source_path: null,
      source_url: null,
      upscaled_assets: [
        {
          id: 102,
          title: 'Stem 1',
          file_path: 'stems/music_stem1.mp3',
          url: 'http://test/stem1.mp3',
        },
        {
          id: 103,
          title: 'Stem 2',
          file_path: 'stems/music_stem2.mp3',
          url: 'http://test/stem2.mp3',
        },
      ],
      tags: [],
      created_at: null,
    },
  ];

  it('computes export counts with and without derivatives', () => {
    const selected = new Set([1, 2]);
    // Asset 1 has 1 derivative, Asset 2 has 0 derivatives
    const withDerivs = computeExportAssetCount(dummyAssets, selected, true);
    assert.equal(withDerivs.selectedCount, 2);
    assert.equal(withDerivs.derivativesCount, 1);
    assert.equal(withDerivs.totalFiles, 3);

    const withoutDerivs = computeExportAssetCount(dummyAssets, selected, false);
    assert.equal(withoutDerivs.selectedCount, 2);
    assert.equal(withoutDerivs.derivativesCount, 0);
    assert.equal(withoutDerivs.totalFiles, 2);
  });

  it('formats export count labels correctly', () => {
    assert.equal(formatExportCountLabel(2, 1, true), '2 assets + 1 derivative');
    assert.equal(formatExportCountLabel(2, 3, true), '2 assets + 3 derivatives');
    assert.equal(formatExportCountLabel(1, 0, true), '1 asset');
    assert.equal(formatExportCountLabel(3, 0, false), '3 assets');
  });

  it('toggles item selection in a Set', () => {
    const set1 = new Set([1, 2]);
    const set2 = toggleItemSelection(set1, 2);
    assert.equal(set2.has(2), false);
    assert.equal(set2.has(1), true);

    const set3 = toggleItemSelection(set2, 3);
    assert.equal(set3.has(3), true);
    assert.equal(set3.has(1), true);
  });

  it('toggles select-all across all IDs', () => {
    const allIds = [1, 2, 3];
    const emptySet = new Set<number>();
    const allSet = toggleSelectAllItems(emptySet, allIds);
    assert.equal(allSet.size, 3);
    assert.equal(isAllItemsSelected(allSet, allIds), true);

    const clearedSet = toggleSelectAllItems(allSet, allIds);
    assert.equal(clearedSet.size, 0);
    assert.equal(isAllItemsSelected(clearedSet, allIds), false);

    const partialSet = new Set([1]);
    const reSelectedAll = toggleSelectAllItems(partialSet, allIds);
    assert.equal(reSelectedAll.size, 3);
  });
});
