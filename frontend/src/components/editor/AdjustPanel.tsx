'use client';
// Adjust panel (#121) — production wiring of the approved Variant A right rail
// (#120): 7 sliders + rotate + crop aspect, Apply/Cancel/Export, undo/redo.
// Every control writes into the editor zustand store (undoable); persistence
// (Apply) and re-render (Export) are owned by the route, not this panel.

import React from 'react';
import { CROP_ASPECTS, SLIDERS, type CropAspect } from '../../utils/editor';
import { useEditorStore } from '../../store/useEditorStore';

export default function AdjustPanel({
  onApply,
  onCancel,
  onExport,
  busy,
}: {
  onApply: () => void;
  onCancel: () => void;
  onExport: () => void;
  busy: boolean;
}) {
  const recipe = useEditorStore((s) => s.recipe);
  const setParam = useEditorStore((s) => s.setParam);
  const undo = useEditorStore((s) => s.undo);
  const redo = useEditorStore((s) => s.redo);
  // MED-02 (#121 review): subscribe to the history arrays directly so the
  // buttons re-render on undo/redo. Calling the method refs during render
  // (useEditorStore((s) => s.canUndo)()) subscribes to the function identity,
  // which never changes, so the disabled state goes stale.
  const canUndo = useEditorStore((s) => s.past.length > 0);
  const canRedo = useEditorStore((s) => s.future.length > 0);

  return (
    <div
      data-testid="adjust-panel"
      className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 space-y-3"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-bold text-slate-200">Adjust</h2>
        <div className="flex gap-1">
          <button
            data-testid="adjust-undo"
            onClick={undo}
            disabled={!canUndo || busy}
            className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-40"
          >
            Undo
          </button>
          <button
            data-testid="adjust-redo"
            onClick={redo}
            disabled={!canRedo || busy}
            className="text-[11px] px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-40"
          >
            Redo
          </button>
        </div>
      </div>

      {SLIDERS.map((s) => (
        <div key={s.key}>
          <div className="flex justify-between text-xs">
            <label htmlFor={`adjust-slider-${s.key}`} className="text-slate-300">
              {s.label}
            </label>
            <span className="font-mono text-sky-400">{recipe[s.key]}</span>
          </div>
          <input
            id={`adjust-slider-${s.key}`}
            data-testid={`adjust-slider-${s.key}`}
            type="range"
            min={s.min}
            max={s.max}
            step={1}
            value={recipe[s.key]}
            disabled={busy}
            onChange={(e) => setParam(s.key, Number(e.target.value))}
            className="w-full accent-sky-500"
          />
        </div>
      ))}

      <div className="flex gap-2 pt-1 items-center">
        <button
          data-testid="adjust-rotate-minus"
          onClick={() => setParam('rotate', Math.max(-45, recipe.rotate - 5))}
          disabled={busy}
          className="text-[11px] px-2 py-1 bg-slate-800 rounded text-slate-200 disabled:opacity-40"
        >
          ⟲ -5°
        </button>
        <span data-testid="adjust-rotate-value" className="text-[11px] font-mono text-sky-400">
          {recipe.rotate}°
        </span>
        <button
          data-testid="adjust-rotate-plus"
          onClick={() => setParam('rotate', Math.min(45, recipe.rotate + 5))}
          disabled={busy}
          className="text-[11px] px-2 py-1 bg-slate-800 rounded text-slate-200 disabled:opacity-40"
        >
          ⟳ +5°
        </button>
        <select
          data-testid="adjust-crop"
          value={recipe.cropAspect}
          disabled={busy}
          onChange={(e) => setParam('cropAspect', e.target.value)}
          className="text-[11px] bg-slate-950 border border-slate-700 rounded px-1 text-slate-200"
          aria-label="Crop aspect"
        >
          {CROP_ASPECTS.map((a: CropAspect) => (
            <option key={a} value={a}>
              crop: {a}
            </option>
          ))}
        </select>
      </div>

      <div className="flex gap-2 pt-2">
        <button
          data-testid="editor-apply"
          onClick={onApply}
          disabled={busy}
          className="flex-1 text-xs font-bold bg-sky-600 hover:bg-sky-500 text-white rounded py-2 disabled:opacity-40"
        >
          Apply
        </button>
        <button
          data-testid="editor-cancel"
          onClick={onCancel}
          disabled={busy}
          className="text-xs px-3 bg-slate-800 rounded py-2 text-slate-200 disabled:opacity-40"
        >
          Cancel
        </button>
        <button
          data-testid="editor-export"
          onClick={onExport}
          disabled={busy}
          className="text-xs px-3 bg-emerald-700 hover:bg-emerald-600 rounded py-2 text-white disabled:opacity-40"
        >
          Export
        </button>
      </div>
    </div>
  );
}
