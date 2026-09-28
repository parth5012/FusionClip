'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Sparkles, X } from 'lucide-react';
import { useStore } from '../../store/useStore';
import {
  fetchMediaCatalog,
  fetchSkinEnhanceSurface,
  startSkinEnhance,
  type SkinEnhanceSurface,
} from '../../utils/api';
import {
  INITIAL_SKIN_SETTINGS,
  buildSkinEnhancePayload,
  parseSkinFailure,
  skinItemStatusText,
  type SkinSettings,
} from '../../utils/skin';
import BeforeAfterModal from '../BeforeAfterModal';
import CompareCanvas from './CompareCanvas';
import ControlRail from './ControlRail';
import ResultsTray from './ResultsTray';
import SourceStrip from './SourceStrip';
import type { SkinItemState, SkinSource } from './types';

const basename = (path: string) => path.split('/').pop() ?? path;

/**
 * Skin Enhancer panel (#113 approved composite, built by #137).
 *
 * `selected` (will be enhanced) and `focused` (shown in the canvas) are
 * distinct: the strip and the results tray both move focus, and the sliders are
 * set once for every selected source. Runs are sequential because the endpoint
 * is synchronous and serializes inference itself; progress is therefore the
 * request lifecycle plus what the response actually reports — no invented
 * percentages, no invented face index.
 */
export default function SkinEnhancerPanel() {
  const { skinTarget, setSkinTarget, activeTab } = useStore();

  const [sources, setSources] = useState<SkinSource[]>([]);
  const [loadingSources, setLoadingSources] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const [focused, setFocused] = useState<string | null>(null);
  const [settings, setSettings] = useState<SkinSettings>(INITIAL_SKIN_SETTINGS);
  const [results, setResults] = useState<Record<string, SkinItemState>>({});
  const [surface, setSurface] = useState<SkinEnhanceSurface | null>(null);
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [showCompare, setShowCompare] = useState(false);
  const initializedRef = useRef<string | null>(null);
  const isMountedRef = useRef(true);

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadSources = useCallback(async () => {
    setLoadingSources(true);
    try {
      const catalog = await fetchMediaCatalog('', 100);
      const images: SkinSource[] = catalog
        .filter((asset) => asset.content_type.toLowerCase().startsWith('image/'))
        .map((asset) => ({ path: asset.file_path, name: basename(asset.file_path), url: asset.url }));
      setSources((prev) => {
        const merged = images.slice();
        if (skinTarget && !merged.some((s) => s.path === skinTarget.path)) {
          merged.unshift({
            path: skinTarget.path,
            name: basename(skinTarget.path),
            url: skinTarget.url,
          });
        }
        // Keep run results and any locally known url when the catalog refreshes.
        return merged.map((next) => {
          const stale = prev.find((s) => s.path === next.path);
          return stale && !next.url ? { ...next, url: stale.url } : next;
        });
      });
    } catch {
      /* backend unreachable — keep whatever we have */
    } finally {
      setLoadingSources(false);
    }
  }, [skinTarget]);

  useEffect(() => {
    loadSources();
  }, [loadSources, activeTab]);

  useEffect(() => {
    fetchSkinEnhanceSurface()
      .then(setSurface)
      .catch(() => setSurface(null));
  }, []);

  // The FileManager action loads this asset: select it and focus it, once per target.
  useEffect(() => {
    if (!skinTarget || initializedRef.current === skinTarget.path) return;
    initializedRef.current = skinTarget.path;
    setSources((prev) =>
      prev.some((s) => s.path === skinTarget.path)
        ? prev
        : [{ path: skinTarget.path, name: basename(skinTarget.path), url: skinTarget.url }, ...prev],
    );
    setSelected([skinTarget.path]);
    setFocused(skinTarget.path);
    setResults({});
    setRunError(null);
  }, [skinTarget]);

  const focusSource = (path: string) => {
    setFocused(path);
    setSelected((prev) => (prev.includes(path) ? prev : [...prev, path]));
  };

  const deselectSource = (path: string) => {
    const next = selected.filter((p) => p !== path);
    setSelected(next);
    if (focused === path) {
      setFocused(next.length ? next[next.length - 1] : null);
    }
    setResults((prev) => {
      if (!prev[path]) return prev;
      const rest = { ...prev };
      delete rest[path];
      return rest;
    });
  };

  const updateSettings = (patch: Partial<SkinSettings>) =>
    setSettings((prev) => ({ ...prev, ...patch }));

  const handleRun = async () => {
    setRunError(null);
    const paths = selected.slice();
    if (paths.length === 0) {
      setRunError('Select at least one source image first.');
      return;
    }
    const probe = buildSkinEnhancePayload(settings, paths[0]);
    if (!probe.ok) {
      setRunError(probe.error);
      return;
    }

    setRunning(true);
    setResults((prev) => {
      const next = { ...prev };
      for (const path of paths) next[path] = { status: 'queued' };
      return next;
    });

    for (const path of paths) {
      if (!isMountedRef.current) break;
      setResults((prev) => ({ ...prev, [path]: { status: 'running' } }));
      const built = buildSkinEnhancePayload(settings, path);
      if (!built.ok) {
        setResults((prev) => ({
          ...prev,
          [path]: { status: 'failed', failure: { slug: null, message: built.error, human: built.error } },
        }));
        continue;
      }
      try {
        const response = await startSkinEnhance(built.payload);
        if (!isMountedRef.current) break;
        if (response.degraded) {
          setResults((prev) => ({
            ...prev,
            [path]: {
              status: 'degraded',
              degraded: {
                reason: response.reason ?? 'degraded',
                message:
                  response.message ||
                  'The local pipeline could not run this job on this host.',
              },
            },
          }));
        } else {
          setResults((prev) => ({
            ...prev,
            [path]: {
              status: 'completed',
              faces: response.faces_enhanced ?? 0,
              resultUrl: response.url,
              engine: response.engine,
            },
          }));
        }
      } catch (err) {
        if (!isMountedRef.current) break;
        const failure = parseSkinFailure(err instanceof Error ? err.message : String(err));
        setResults((prev) => ({ ...prev, [path]: { status: 'failed', failure } }));
      }
    }

    if (!isMountedRef.current) return;
    setRunning(false);
    loadSources();
  };

  const focusedSource = sources.find((s) => s.path === focused) ?? null;
  const focusedItem = focused ? results[focused] : undefined;
  const focusedStatus = focusedItem?.status ?? 'queued';
  const canCompare = Boolean(
    focusedSource?.url && focusedItem?.status === 'completed' && focusedItem.resultUrl,
  );
  const trayItems = selected.map((path) => ({
    source:
      sources.find((s) => s.path === path) ?? { path, name: basename(path), url: undefined },
    item: results[path],
  }));

  const presetList = surface
    ? Object.keys(surface.presets).map((id) => ({
        id,
        label: id,
        blurb: surface.presets[id].description,
      }))
    : undefined;

  return (
    <div
      className="fixed inset-0 z-50 overflow-y-auto bg-slate-950/92 p-4 backdrop-blur-sm"
      data-testid="skin-enhancer-panel"
    >
      <div className="mx-auto max-w-6xl rounded-xl border border-amber-500/30 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-2.5">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-300" />
            <span className="text-xs font-semibold text-slate-100">Skin Enhancer</span>
            <span className="font-mono text-[10px] text-slate-500">
              {loadingSources ? 'loading catalog…' : `${sources.length} images · ${selected.length} selected`}
            </span>
          </div>
          <button
            type="button"
            onClick={() => setSkinTarget(null)}
            aria-label="Close skin enhancer"
            className="rounded p-1 text-slate-400 transition hover:bg-slate-800 hover:text-white"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <SourceStrip
          sources={sources}
          selected={selected}
          focused={focused}
          onFocus={focusSource}
          onDeselect={deselectSource}
          disabled={running}
        />

        <div className="grid grid-cols-1 lg:grid-cols-[1.55fr_1fr]">
          <div>
            <CompareCanvas
              source={focusedSource}
              item={focusedItem}
              statusText={skinItemStatusText({ status: focusedStatus }, settings.mode)}
            />
            <ResultsTray
              items={trayItems}
              focused={focused}
              onFocus={(path) => setFocused(path)}
              mode={settings.mode}
            />
          </div>

          <ControlRail
            settings={settings}
            onChange={updateSettings}
            presets={presetList}
            skinDetailSemantics={
              surface?.skin_detail_semantics?.[settings.mode] ?? undefined
            }
            running={running}
            selectedCount={selected.length}
            onRun={handleRun}
            onFullscreen={() => setShowCompare(true)}
            canFullscreen={canCompare}
            error={runError}
          />
        </div>
      </div>

      {showCompare && canCompare && focusedSource?.url && focusedItem?.resultUrl && (
        <BeforeAfterModal
          beforeUrl={focusedSource.url}
          afterUrl={focusedItem.resultUrl}
          title={`Skin Enhancer · ${focusedSource.name}`}
          beforeLabel="Before"
          afterLabel="Enhanced"
          onClose={() => setShowCompare(false)}
        />
      )}
    </div>
  );
}
