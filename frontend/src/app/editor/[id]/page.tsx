'use client';
// Production editor route (#121) — /editor/[id] with the approved Variant A
// layout (#120): canvas left, Adjust rail right. [id] is the MediaAsset id;
// the asset resolves through the existing media catalog (no new backend read
// needed for loading). Apply persists a versioned edit-recipe JSON, Export
// runs the authoritative server re-render, and reload replays the latest
// saved version (edit-save-reload fidelity).

import React, { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import AdjustPanel from '../../../components/editor/AdjustPanel';
import EditorCanvas from '../../../components/editor/EditorCanvas';
import { useEditorStore } from '../../../store/useEditorStore';
import {
  DEFAULT_RECIPE,
  fetchEditorRecipes,
  renderEditorImage,
  saveEditorRecipe,
  validateRecipe,
  type EditorRecipe,
  type EditorRenderResponse,
} from '../../../utils/editor';
import { fetchMediaCatalog, type MediaAsset } from '../../../utils/api';

function isImageAsset(asset: MediaAsset): boolean {
  if ((asset.content_type || '').toLowerCase().startsWith('image/')) return true;
  return /\.(png|jpe?g|webp|gif|bmp|tiff?)$/i.test(asset.file_path || '');
}

export default function EditorPage() {
  const params = useParams();
  const id = Array.isArray(params.id) ? params.id[0] : params.id;

  const recipe = useEditorStore((s) => s.recipe);
  const load = useEditorStore((s) => s.load);

  const [asset, setAsset] = useState<MediaAsset | null>(null);
  const [savedRecipe, setSavedRecipe] = useState<EditorRecipe>({ ...DEFAULT_RECIPE });
  const [savedVersion, setSavedVersion] = useState<number | null>(null);
  const [exportResult, setExportResult] = useState<EditorRenderResponse | null>(null);
  const [status, setStatus] = useState<string>('Loading…');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  // Load leg: asset by id, then the latest saved recipe version (if any).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // MED-03 (#121 review): the default catalog limit is 20 — an asset
        // past the first page would 404 as "not found". Fetch up to 100.
        const catalog = await fetchMediaCatalog('', 100);
        const found = catalog.find((a) => String(a.id) === String(id));
        if (!found) {
          if (!cancelled) {
            setFailed(true);
            setStatus(`Asset ${id} was not found in the catalog.`);
          }
          return;
        }
        if (!isImageAsset(found)) {
          if (!cancelled) {
            setFailed(true);
            setStatus(`Asset ${found.file_path} is not an image — the editor is images only in v1.`);
          }
          return;
        }
        const versions = await fetchEditorRecipes(found.file_path).catch(() => []);
        if (cancelled) return;
        setAsset(found);
        const latest = versions.length > 0 ? versions[versions.length - 1] : null;
        if (latest) {
          const checked = validateRecipe(latest.recipe);
          const restored = checked.ok ? checked.recipe : { ...DEFAULT_RECIPE };
          load(restored);
          setSavedRecipe(restored);
          setSavedVersion(latest.version);
          setStatus(`Loaded version ${latest.version} for ${found.file_path}.`);
        } else {
          load({ ...DEFAULT_RECIPE });
          setSavedRecipe({ ...DEFAULT_RECIPE });
          setSavedVersion(null);
          setStatus(`Opened ${found.file_path} — no saved versions yet.`);
        }
      } catch (err) {
        if (!cancelled) {
          setFailed(true);
          setStatus(err instanceof Error ? err.message : 'Failed to load the editor.');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, load]);

  const handleApply = useCallback(async () => {
    if (!asset) return;
    const checked = validateRecipe(recipe);
    if (!checked.ok) {
      setStatus(checked.error);
      return;
    }
    setBusy(true);
    setStatus('Saving recipe…');
    try {
      const saved = await saveEditorRecipe(asset.file_path, checked.recipe);
      load(saved.recipe);
      setSavedRecipe(saved.recipe);
      setSavedVersion(saved.version);
      setStatus(`Saved version ${saved.version} for ${asset.file_path}.`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Failed to save edit recipe.');
    } finally {
      setBusy(false);
    }
  }, [asset, recipe, load]);

  const handleCancel = useCallback(() => {
    load({ ...savedRecipe });
    setStatus(
      savedVersion === null
        ? 'Reverted to defaults (nothing saved yet).'
        : `Reverted to saved version ${savedVersion}.`,
    );
  }, [load, savedRecipe, savedVersion]);

  const handleExport = useCallback(async () => {
    if (!asset) return;
    const checked = validateRecipe(recipe);
    if (!checked.ok) {
      setStatus(checked.error);
      return;
    }
    setBusy(true);
    setStatus('Rendering export…');
    try {
      const rendered = await renderEditorImage(asset.file_path, checked.recipe);
      setExportResult(rendered);
      // Export co-saves its recipe as a new version — adopt it as saved.
      load(rendered.parameters);
      setSavedRecipe(rendered.parameters);
      setSavedVersion(rendered.version);
      setStatus(`Exported ${rendered.filename} (version ${rendered.version}).`);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : 'Failed to render export.');
    } finally {
      setBusy(false);
    }
  }, [asset, recipe, load]);

  return (
    <div data-testid="editor-page" className="min-h-screen bg-slate-950 text-slate-100 px-4 py-6 max-w-7xl mx-auto">
      <h1 className="text-lg font-bold">Image Editor</h1>
      <p className="text-xs text-slate-400 mb-4">
        Non-destructive Adjust — preview left, controls right. Apply saves a versioned recipe; Export re-renders on the server.
      </p>

      <div data-testid="editor-status" role="status" className="text-xs text-slate-300 mb-3">
        {status}
      </div>
      {savedVersion !== null && (
        <div data-testid="editor-saved-version" className="text-[11px] font-mono text-emerald-400 mb-3">
          saved version {savedVersion}
        </div>
      )}

      {failed || !asset ? (
        failed ? (
          // LOW-01 (#121 review): a failed load must render an error card,
          // not an empty container.
          <div
            data-testid="editor-error"
            role="alert"
            className="bg-red-950/60 border border-red-800 rounded-xl p-4 text-xs text-red-200"
          >
            <div className="font-bold mb-1">Could not load the editor</div>
            <div>{status}</div>
          </div>
        ) : (
          <div className="text-xs text-slate-400">Loading asset…</div>
        )
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          <div className="lg:col-span-8">
            <EditorCanvas src={asset.url} alt={asset.file_path} />
            {exportResult && (
              <div className="mt-3 bg-slate-900/70 border border-emerald-900 rounded-xl p-4">
                <div className="text-xs font-bold text-emerald-300 mb-2">Exported render</div>
                <div className="grid grid-cols-2 gap-2 text-[11px] text-slate-400">
                  <div>
                    <div className="mb-1">Before (original)</div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={asset.url} alt="original" className="w-full rounded border border-slate-700" />
                  </div>
                  <div>
                    <div className="mb-1">After (rendered)</div>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={exportResult.url} alt="rendered export" className="w-full rounded border border-slate-700" />
                  </div>
                </div>
                <a
                  data-testid="editor-export-url"
                  href={exportResult.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[11px] font-mono text-sky-400 break-all"
                >
                  {exportResult.filename}
                </a>
              </div>
            )}
          </div>
          <div className="lg:col-span-4">
            <AdjustPanel onApply={handleApply} onCancel={handleCancel} onExport={handleExport} busy={busy} />
          </div>
        </div>
      )}
    </div>
  );
}
