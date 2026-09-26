import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { filterAssetsByTags, extractAllTags } from './tags';
import type { MediaAsset } from './api';

describe('filterAssetsByTags', () => {
  const dummyAssets: MediaAsset[] = [
    {
      id: 1,
      title: 'Sunset Drone Footage',
      file_path: 'drone_sunset.mp4',
      file_size: 1024,
      content_type: 'video/mp4',
      duration: 10,
      url: 'http://test/drone_sunset.mp4',
      source_path: null,
      source_url: null,
      upscaled_assets: [],
      created_at: null,
      tags: [
        { id: 1, name: 'sunset' },
        { id: 2, name: 'drone' },
      ],
    },
    {
      id: 2,
      title: 'Beach Sunset Picture',
      file_path: 'beach_sunset.jpg',
      file_size: 512,
      content_type: 'image/jpeg',
      duration: 0,
      url: 'http://test/beach_sunset.jpg',
      source_path: null,
      source_url: null,
      upscaled_assets: [],
      created_at: null,
      tags: [
        { id: 1, name: 'sunset' },
        { id: 3, name: 'beach' },
      ],
    },
    {
      id: 3,
      title: 'City Drone Flyby',
      file_path: 'city_drone.mp4',
      file_size: 2048,
      content_type: 'video/mp4',
      duration: 15,
      url: 'http://test/city_drone.mp4',
      source_path: null,
      source_url: null,
      upscaled_assets: [],
      created_at: null,
      tags: [
        { id: 2, name: 'drone' },
        { id: 4, name: 'city' },
      ],
    },
    {
      id: 4,
      title: 'Untagged Audio',
      file_path: 'music.mp3',
      file_size: 256,
      content_type: 'audio/mpeg',
      duration: 30,
      url: 'http://test/music.mp3',
      source_path: null,
      source_url: null,
      upscaled_assets: [],
      created_at: null,
      tags: [],
    },
  ];

  it('returns all assets when selectedTags is empty', () => {
    const result = filterAssetsByTags(dummyAssets, []);
    assert.equal(result.length, 4);
  });

  it('filters assets by a single tag', () => {
    const sunsets = filterAssetsByTags(dummyAssets, ['sunset']);
    assert.equal(sunsets.length, 2);
    assert.deepEqual(sunsets.map(a => a.id), [1, 2]);

    const drones = filterAssetsByTags(dummyAssets, ['drone']);
    assert.equal(drones.length, 2);
    assert.deepEqual(drones.map(a => a.id), [1, 3]);
  });

  it('filters assets with AND semantics across multiple tags', () => {
    const sunsetDrone = filterAssetsByTags(dummyAssets, ['sunset', 'drone']);
    assert.equal(sunsetDrone.length, 1);
    assert.equal(sunsetDrone[0].id, 1);

    const sunsetCity = filterAssetsByTags(dummyAssets, ['sunset', 'city']);
    assert.equal(sunsetCity.length, 0);
  });

  it('is case-insensitive when matching tags', () => {
    const result = filterAssetsByTags(dummyAssets, ['SUNSET', 'Drone']);
    assert.equal(result.length, 1);
    assert.equal(result[0].id, 1);
  });

  it('extracts all unique tags with usage counts', () => {
    const tagSummary = extractAllTags(dummyAssets);
    assert.deepEqual(tagSummary, [
      { name: 'drone', count: 2 },
      { name: 'sunset', count: 2 },
      { name: 'beach', count: 1 },
      { name: 'city', count: 1 },
    ]);
  });
});
