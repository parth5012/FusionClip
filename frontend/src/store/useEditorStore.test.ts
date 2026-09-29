import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { useEditorStore, MAX_UNDO_SNAPSHOTS } from './useEditorStore';
import { DEFAULT_RECIPE } from '../utils/editor';

describe('editor undo store (#121: ~50 zustand snapshots)', () => {
  beforeEach(() => {
    useEditorStore.getState().reset();
  });

  it('starts at the default recipe with empty history', () => {
    const s = useEditorStore.getState();
    assert.deepEqual(s.recipe, DEFAULT_RECIPE);
    assert.equal(s.canUndo(), false);
    assert.equal(s.canRedo(), false);
  });

  it('setParam pushes a snapshot; undo restores; redo re-applies', () => {
    useEditorStore.getState().setParam('exposure', 25);
    assert.equal(useEditorStore.getState().recipe.exposure, 25);
    assert.equal(useEditorStore.getState().canUndo(), true);

    useEditorStore.getState().undo();
    assert.equal(useEditorStore.getState().recipe.exposure, 0);
    assert.equal(useEditorStore.getState().canRedo(), true);

    useEditorStore.getState().redo();
    assert.equal(useEditorStore.getState().recipe.exposure, 25);
  });

  it('a new edit after undo drops the redo branch', () => {
    const api = useEditorStore.getState();
    api.setParam('exposure', 10);
    api.setParam('contrast', 20);
    useEditorStore.getState().undo();
    useEditorStore.getState().setParam('tint', 5);
    const s = useEditorStore.getState();
    assert.equal(s.recipe.contrast, 0);
    assert.equal(s.recipe.tint, 5);
    assert.equal(s.canRedo(), false);
  });

  it('caps history at ~50 snapshots', () => {
    assert.equal(MAX_UNDO_SNAPSHOTS, 50);
    for (let i = 1; i <= 60; i++) {
      useEditorStore.getState().setParam('exposure', (i % 21) - 10);
    }
    const s = useEditorStore.getState();
    assert.ok(s.past.length <= MAX_UNDO_SNAPSHOTS);
    // Oldest history was dropped, but undo still works from here.
    s.undo();
    assert.equal(useEditorStore.getState().canRedo(), true);
  });

  it('no-op sets push no snapshot', () => {
    useEditorStore.getState().setParam('exposure', 0);
    assert.equal(useEditorStore.getState().canUndo(), false);
  });

  it('load replaces the recipe and resets history', () => {
    useEditorStore.getState().setParam('exposure', 30);
    useEditorStore.getState().load({ ...DEFAULT_RECIPE, grain: 40 });
    const s = useEditorStore.getState();
    assert.equal(s.recipe.grain, 40);
    assert.equal(s.recipe.exposure, 0);
    assert.equal(s.canUndo(), false);
    assert.equal(s.canRedo(), false);
  });
});
