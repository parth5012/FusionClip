'use client';

import React, { useState, useEffect, useMemo, useRef } from 'react';
import { 
  Search, Volume2, Video, Image as ImageIcon, File, 
  Loader2, ArrowUpRight, Calendar, HardDrive, RefreshCw, X, Clock, ArrowLeftRight,
  Tag as TagIcon, LayoutGrid, List, Plus, Check, Download, CheckCircle2, AlertCircle
} from 'lucide-react';
import { fetchMediaCatalog, addAssetTag, removeAssetTag, MediaAsset, startAssetBatchExport, getExportStatus, triggerDownload } from '../utils/api';
import { filterAssetsByTags, extractAllTags } from '../utils/tags';
import {
  computeExportAssetCount,
  formatExportCountLabel,
  toggleItemSelection,
  toggleSelectAllItems,
  isAllItemsSelected,
} from '../utils/export';
import BeforeAfterModal from './BeforeAfterModal';

export default function CatalogPanel() {
  const [query, setQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [mediaList, setMediaList] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState<'all' | 'audio' | 'video' | 'image'>('all');
  
  // Grid / List view mode (#105)
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid');
  
  // Tag filter state with AND semantics (#105)
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  
  // Sorting state (#105)
  const [sortBy, setSortBy] = useState<'newest' | 'oldest' | 'name-asc' | 'name-desc' | 'size-desc'>('newest');
  
  // Inline tag addition state (#105)
  const [addingTagAssetId, setAddingTagAssetId] = useState<number | null>(null);
  const [newTagName, setNewTagName] = useState('');
  const [tagActionLoading, setTagActionLoading] = useState<number | null>(null);
  const [tagError, setTagError] = useState<{ assetId: number; message: string } | null>(null);

  // Request sequencing guard (#131)
  const catalogRequestId = useRef(0);

  // Before/after comparison (map #58): pairs a source asset with its upscaled output.
  const [compare, setCompare] = useState<{ beforeUrl: string; afterUrl: string; title: string } | null>(null);

  // Batch export selection state (#106)
  const [selectedAssetIds, setSelectedAssetIds] = useState<Set<number>>(new Set());
  const [includeDerivatives, setIncludeDerivatives] = useState<boolean>(true);
  const [exporting, setExporting] = useState<boolean>(false);
  const [exportProgress, setExportProgress] = useState<number>(0);
  const [exportStatusText, setExportStatusText] = useState<string>('');
  const [exportDownloadUrl, setExportDownloadUrl] = useState<string | null>(null);
  const [exportFilename, setExportFilename] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [activeExportTaskId, setActiveExportTaskId] = useState<string | null>(null);

  const loadCatalog = async (searchQuery = activeSearch, tagsToApply = selectedTags) => {
    const requestId = ++catalogRequestId.current;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMediaCatalog(searchQuery, 20, tagsToApply);
      if (catalogRequestId.current !== requestId) return;
      setMediaList(data);
      setActiveSearch(searchQuery);
    } catch (err: any) {
      if (catalogRequestId.current !== requestId) return;
      console.error(err);
      setError(err.message || 'Failed to search or load catalog assets.');
    } finally {
      if (catalogRequestId.current === requestId) {
        setLoading(false);
      }
    }
  };

  useEffect(() => {
    loadCatalog('', []);
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadCatalog(query, selectedTags);
  };

  const handleClearSearch = () => {
    setQuery('');
    loadCatalog('', selectedTags);
  };

  // Helper formatting size
  const formatSize = (bytes?: number) => {
    if (bytes === undefined || bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  // Helper formatting seconds
  const formatDuration = (seconds?: number) => {
    if (!seconds || seconds <= 0) return '';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs < 10 ? '0' : ''}${secs}`;
  };

  // Tag filter handlers
  const toggleTagFilter = (tagName: string) => {
    const norm = tagName.trim().toLowerCase();
    const nextTags = selectedTags.includes(norm)
      ? selectedTags.filter(t => t !== norm)
      : [...selectedTags, norm];
    setSelectedTags(nextTags);
    if (activeSearch) {
      loadCatalog(activeSearch, nextTags);
    }
  };

  const clearTagFilters = () => {
    setSelectedTags([]);
    if (activeSearch) {
      loadCatalog(activeSearch, []);
    }
  };

  // Inline tag addition and removal
  const handleAddTag = async (assetId: number) => {
    const trimmed = newTagName.trim();
    if (!trimmed) {
      setAddingTagAssetId(null);
      setTagError(null);
      return;
    }
    if (trimmed.includes(',')) {
      setTagError({ assetId, message: 'Tag name cannot contain commas' });
      return;
    }
    if (trimmed.length > 64) {
      setTagError({ assetId, message: 'Tag name cannot exceed 64 characters' });
      return;
    }
    setTagActionLoading(assetId);
    setTagError(null);
    try {
      const res = await addAssetTag(assetId, trimmed);
      setMediaList(prev => prev.map(asset => {
        if (asset.id === assetId) {
          return { ...asset, tags: res.tags };
        }
        return asset;
      }));
      setNewTagName('');
      setAddingTagAssetId(null);
      setTagError(null);
    } catch (err: any) {
      console.error('Failed to add tag:', err);
      setTagError({ assetId, message: err.message || 'Failed to add tag' });
    } finally {
      setTagActionLoading(null);
    }
  };

  const handleRemoveTag = async (assetId: number, tagId: number) => {
    setTagActionLoading(assetId);
    setTagError(null);
    try {
      const res = await removeAssetTag(assetId, tagId);
      setMediaList(prev => prev.map(asset => {
        if (asset.id === assetId) {
          return { ...asset, tags: res.tags };
        }
        return asset;
      }));
      setTagError(null);
    } catch (err: any) {
      console.error('Failed to remove tag:', err);
      setTagError({ assetId, message: err.message || 'Failed to remove tag' });
    } finally {
      setTagActionLoading(null);
    }
  };

  // Filter 1: Type filter (audio, video, image)
  const typeFiltered = useMemo(() => {
    return mediaList.filter(item => {
      const type = item.content_type.toLowerCase();
      if (selectedFilter === 'audio') return type.startsWith('audio/');
      if (selectedFilter === 'video') return type.startsWith('video/');
      if (selectedFilter === 'image') return type.startsWith('image/');
      return true;
    });
  }, [mediaList, selectedFilter]);

  // Extract all unique tags present across assets
  const availableTags = useMemo(() => {
    return extractAllTags(typeFiltered);
  }, [typeFiltered]);

  // Filter 2: Tag filter (AND semantics across selected tags)
  const tagFiltered = useMemo(() => {
    return filterAssetsByTags(typeFiltered, selectedTags);
  }, [typeFiltered, selectedTags]);

  // Sort
  const sortedList = useMemo(() => {
    return [...tagFiltered].sort((a, b) => {
      if (sortBy === 'newest') {
        const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tB - tA;
      }
      if (sortBy === 'oldest') {
        const tA = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tB = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tA - tB;
      }
      if (sortBy === 'name-asc') {
        return a.title.localeCompare(b.title);
      }
      if (sortBy === 'name-desc') {
        return b.title.localeCompare(a.title);
      }
      if (sortBy === 'size-desc') {
        return (b.file_size || 0) - (a.file_size || 0);
      }
      return 0;
    });
  }, [tagFiltered, sortBy]);

  // Calculate totals for badges
  const counts = {
    all: mediaList.length,
    audio: mediaList.filter(item => item.content_type.toLowerCase().startsWith('audio/')).length,
    video: mediaList.filter(item => item.content_type.toLowerCase().startsWith('video/')).length,
    image: mediaList.filter(item => item.content_type.toLowerCase().startsWith('image/')).length,
  };

  // Selection handlers (#106)
  const handleToggleSelectAsset = (id: number) => {
    setSelectedAssetIds((prev) => toggleItemSelection(prev, id));
  };

  const handleToggleSelectAll = () => {
    const allIds = sortedList.map((a) => a.id);
    setSelectedAssetIds((prev) => toggleSelectAllItems(prev, allIds));
  };

  const handleClearSelection = () => {
    setSelectedAssetIds(new Set());
  };

  const exportSummary = useMemo(() => {
    return computeExportAssetCount(sortedList, selectedAssetIds, includeDerivatives);
  }, [sortedList, selectedAssetIds, includeDerivatives]);

  const handleStartExport = async () => {
    if (selectedAssetIds.size === 0) return;
    setExporting(true);
    setExportProgress(0);
    setExportError(null);
    setExportDownloadUrl(null);
    setExportFilename(null);
    setExportStatusText('Initiating export job...');
    try {
      const res = await startAssetBatchExport(
        Array.from(selectedAssetIds),
        includeDerivatives
      );
      setActiveExportTaskId(res.task_id);
      setExportStatusText('Preparing ZIP archive in background...');
    } catch (err: any) {
      setExportError(err.message || 'Failed to initiate batch export');
      setExporting(false);
    }
  };

  // Poll export task status (#106)
  useEffect(() => {
    if (!activeExportTaskId) return;

    const interval = setInterval(async () => {
      try {
        const status = await getExportStatus(activeExportTaskId);
        setExportProgress(status.progress);
        if (status.status === 'COMPLETED') {
          setExportStatusText('ZIP archive ready!');
          setExportDownloadUrl(status.download_url ?? null);
          setExportFilename(status.filename ?? 'export.zip');
          setExporting(false);
          setActiveExportTaskId(null);
          if (status.download_url) {
            triggerDownload(status.download_url, status.filename ?? undefined);
          }
        } else if (status.status === 'FAILED') {
          setExportError(status.error || 'Batch export task failed');
          setExporting(false);
          setActiveExportTaskId(null);
        } else if (status.status === 'PROCESSING') {
          setExportStatusText(`Zipping archive... ${status.progress}%`);
        }
      } catch (err: any) {
        console.error('Error polling export status:', err);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [activeExportTaskId]);

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Unified Media Catalog</h2>
          <p className="text-xs text-slate-400">
            View, filter, tag, and sort uploaded and generated media assets with vector semantic search.
          </p>
        </div>

        {/* View Mode Switcher (Grid vs List) */}
        <div className="flex items-center gap-1 bg-slate-900 border border-slate-800 p-1 rounded-lg self-start sm:self-auto">
          <button
            onClick={() => setViewMode('grid')}
            className={`p-2 rounded flex items-center gap-1.5 text-xs font-medium transition ${
              viewMode === 'grid'
                ? 'bg-sky-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
            title="Grid View"
          >
            <LayoutGrid className="w-4 h-4" />
            <span className="hidden sm:inline">Grid</span>
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-2 rounded flex items-center gap-1.5 text-xs font-medium transition ${
              viewMode === 'list'
                ? 'bg-sky-600 text-white shadow'
                : 'text-slate-400 hover:text-slate-200'
            }`}
            title="List View"
          >
            <List className="w-4 h-4" />
            <span className="hidden sm:inline">List</span>
          </button>
        </div>
      </div>

      {/* Search Bar Input */}
      <form onSubmit={handleSearchSubmit} className="bg-slate-900 border border-slate-800 p-4 rounded-lg flex flex-col md:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            className="w-full bg-slate-950 border border-slate-700 pl-10 pr-10 py-2.5 rounded-md text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500 transition"
            placeholder="Ask me anything (e.g., 'synthesized ElevenLabs sound', 'flux sandboxes', 'bunny video')..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {query && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="absolute right-3.5 top-1/2 -translate-y-1/2 p-0.5 text-slate-500 hover:text-slate-350 cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={loading}
            className="flex items-center justify-center gap-2 bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-semibold text-sm px-6 py-2.5 rounded-md transition"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
          {activeSearch && (
            <button
              type="button"
              onClick={handleClearSearch}
              className="flex items-center justify-center gap-2 border border-slate-700 hover:bg-slate-800 text-slate-300 text-sm px-4 py-2.5 rounded-md transition"
            >
              Reset
            </button>
          )}
        </div>
      </form>

      {/* Filter and metadata toolbar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 bg-slate-900 border border-slate-850 p-3 rounded-lg overflow-x-auto">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setSelectedFilter('all')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${
              selectedFilter === 'all'
                ? 'bg-sky-950 text-sky-400 border border-sky-850'
                : 'text-slate-400 hover:text-slate-200 border border-transparent'
            }`}
          >
            All Media ({counts.all})
          </button>
          <button
            onClick={() => setSelectedFilter('video')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${
              selectedFilter === 'video'
                ? 'bg-indigo-950 text-indigo-400 border border-indigo-900'
                : 'text-slate-400 hover:text-slate-205 border border-transparent'
            }`}
          >
            Video ({counts.video})
          </button>
          <button
            onClick={() => setSelectedFilter('audio')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${
              selectedFilter === 'audio'
                ? 'bg-amber-950 text-amber-400 border border-amber-900'
                : 'text-slate-400 hover:text-slate-205 border border-transparent'
            }`}
          >
            Audio ({counts.audio})
          </button>
          <button
            onClick={() => setSelectedFilter('image')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition ${
              selectedFilter === 'image'
                ? 'bg-emerald-950 text-emerald-400 border border-emerald-900'
                : 'text-slate-400 hover:text-slate-205 border border-transparent'
            }`}
          >
            Image ({counts.image})
          </button>
        </div>

        {/* Sort dropdown and refresh */}
        <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
          <div className="flex items-center gap-1.5 text-xs text-slate-400">
            <span>Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => setSortBy(e.target.value as any)}
              className="bg-slate-950 border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"
            >
              <option value="newest">Newest first</option>
              <option value="oldest">Oldest first</option>
              <option value="name-asc">Title (A-Z)</option>
              <option value="name-desc">Title (Z-A)</option>
              <option value="size-desc">File size (largest)</option>
            </select>
          </div>

          <button
            onClick={() => loadCatalog(activeSearch, selectedTags)}
            className="p-2 border border-slate-700 bg-slate-950/40 rounded text-slate-400 hover:bg-slate-800 transition text-xs flex items-center gap-1.5"
            title="Refresh catalog list"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Refresh</span>
          </button>
        </div>
      </div>

      {/* Tag Filtering Bar (#105) */}
      <div className="bg-slate-900/80 border border-slate-800/80 p-3.5 rounded-lg space-y-2.5">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2 text-xs font-semibold text-slate-300">
            <TagIcon className="w-3.5 h-3.5 text-sky-400" />
            <span>Filter by Tags:</span>
            {selectedTags.length > 0 && (
              <span className="text-[11px] font-normal text-sky-400 bg-sky-950/60 border border-sky-850 px-2 py-0.5 rounded">
                Matching ALL ({selectedTags.length} selected &bull; AND semantics)
              </span>
            )}
          </div>
          {selectedTags.length > 0 && (
            <button
              onClick={clearTagFilters}
              className="text-xs text-rose-400 hover:text-rose-300 underline underline-offset-2 flex items-center gap-1 transition"
            >
              <X className="w-3 h-3" /> Clear tag filters
            </button>
          )}
        </div>

        {availableTags.length === 0 ? (
          <p className="text-xs text-slate-500 italic">
            No tags found in catalog. Add tags inline to assets below.
          </p>
        ) : (
          <div className="flex flex-wrap gap-1.5 pt-1">
            {availableTags.map(({ name, count }) => {
              const isSelected = selectedTags.includes(name);
              return (
                <button
                  key={name}
                  onClick={() => toggleTagFilter(name)}
                  className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition ${
                    isSelected
                      ? 'bg-sky-600 text-white shadow-sm ring-1 ring-sky-400'
                      : 'bg-slate-800 hover:bg-slate-750 text-slate-300 border border-slate-700 hover:border-slate-600'
                  }`}
                >
                  <span>#{name}</span>
                  <span className={`text-[10px] px-1 rounded-full ${isSelected ? 'bg-sky-700 text-sky-100' : 'bg-slate-900 text-slate-400'}`}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Active Search Text Alert */}
      {activeSearch && (
        <div className="bg-sky-950/20 border border-sky-900/60 rounded p-3 text-xs text-sky-400 flex items-center justify-between">
          <span>
            Semantic search results matching:&nbsp;
            <strong className="text-slate-100 underline decoration-sky-600 font-semibold">{activeSearch}</strong>
          </span>
          <button onClick={handleClearSearch} className="hover:text-slate-100 transition">
            Close Results
          </button>
        </div>
      )}

      {/* Batch Export Progress / Status Banner (#106) */}
      {(exporting || exportDownloadUrl || exportError) && (
        <div className="rounded-lg overflow-hidden border border-slate-800 transition">
          {exporting && (
            <div className="bg-slate-900 border-sky-800/80 p-4 space-y-2.5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-sky-300 font-medium">
                  <Loader2 className="w-4 h-4 animate-spin text-sky-400" />
                  <span>{exportStatusText}</span>
                </div>
                <span className="text-xs font-mono text-slate-400">{exportProgress}%</span>
              </div>
              <div className="w-full bg-slate-950 rounded-full h-1.5 overflow-hidden">
                <div
                  className="bg-sky-500 h-1.5 rounded-full transition-all duration-300"
                  style={{ width: `${exportProgress}%` }}
                />
              </div>
            </div>
          )}

          {exportDownloadUrl && (
            <div className="bg-emerald-950/40 border-emerald-800 p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
              <div className="flex items-center gap-2.5 text-sm text-emerald-300 font-medium">
                <CheckCircle2 className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                <div>
                  <p>Batch export archive ready!</p>
                  <p className="text-xs text-emerald-400/80 font-mono">{exportFilename}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 self-end sm:self-auto">
                <button
                  onClick={() => triggerDownload(exportDownloadUrl, exportFilename ?? undefined)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-semibold shadow transition"
                >
                  <Download className="w-3.5 h-3.5" />
                  Download ZIP
                </button>
                <button
                  onClick={() => {
                    setExportDownloadUrl(null);
                    setExportFilename(null);
                  }}
                  className="p-1.5 text-slate-400 hover:text-slate-200 transition"
                  title="Dismiss"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {exportError && (
            <div className="bg-rose-950/40 border-rose-800 p-4 flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-sm text-rose-300">
                <AlertCircle className="w-5 h-5 text-rose-400 flex-shrink-0" />
                <span>{exportError}</span>
              </div>
              <button
                onClick={() => setExportError(null)}
                className="p-1 text-slate-400 hover:text-slate-200 transition"
                title="Dismiss"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          )}
        </div>
      )}

      {/* Batch Selection & Export Action Bar (#106) */}
      {!loading && !error && sortedList.length > 0 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 bg-slate-900/90 border border-slate-800 p-3 rounded-lg text-xs">
          <div className="flex items-center gap-3 flex-wrap">
            <label className="flex items-center gap-2 text-slate-300 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={isAllItemsSelected(selectedAssetIds, sortedList.map(a => a.id))}
                onChange={handleToggleSelectAll}
                className="w-4 h-4 rounded bg-slate-950 border-slate-700 text-sky-600 focus:ring-sky-500 cursor-pointer"
              />
              <span className="font-medium">Select All ({sortedList.length})</span>
            </label>

            {selectedAssetIds.size > 0 && (
              <>
                <span className="text-slate-600">|</span>
                <span className="text-sky-400 font-semibold bg-sky-950/70 border border-sky-850 px-2.5 py-0.5 rounded-full">
                  {formatExportCountLabel(exportSummary.selectedCount, exportSummary.derivativesCount, includeDerivatives)}
                </span>
                <button
                  onClick={handleClearSelection}
                  className="text-slate-400 hover:text-rose-300 transition underline underline-offset-2"
                >
                  Clear selection
                </button>
              </>
            )}
          </div>

          <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end">
            <label className="flex items-center gap-1.5 text-slate-400 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeDerivatives}
                onChange={(e) => setIncludeDerivatives(e.target.checked)}
                className="w-3.5 h-3.5 rounded bg-slate-950 border-slate-700 text-sky-600 focus:ring-sky-500 cursor-pointer"
              />
              <span>Include derivatives</span>
            </label>

            <button
              onClick={handleStartExport}
              disabled={selectedAssetIds.size === 0 || exporting}
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 bg-sky-600 hover:bg-sky-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold rounded transition shadow-sm"
              title={selectedAssetIds.size === 0 ? "Select assets to export" : "Export ZIP archive"}
            >
              {exporting ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Download className="w-3.5 h-3.5" />
              )}
              <span>Export ZIP {selectedAssetIds.size > 0 && `(${exportSummary.totalFiles})`}</span>
            </button>
          </div>
        </div>
      )}

      {/* Main Content: Grid or List */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 bg-slate-900/40 border border-slate-850 rounded-lg">
          <Loader2 className="w-8 h-8 animate-spin text-sky-500" />
          <p className="text-slate-400 text-sm mt-3">Executing semantic vector index match query...</p>
        </div>
      ) : error ? (
        <div className="bg-rose-950/15 border border-rose-850 rounded-lg p-8 text-center">
          <p className="text-rose-400 font-semibold text-lg">Query Integration Failure</p>
          <p className="text-xs text-rose-350 mt-1 opacity-90">{error}</p>
          <button
            onClick={() => loadCatalog(activeSearch, selectedTags)}
            className="mt-4 px-4 py-2 bg-rose-900/40 hover:bg-rose-900/60 border border-rose-800 text-slate-200 rounded text-xs transition"
          >
            Retry Query
          </button>
        </div>
      ) : sortedList.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 bg-slate-900/30 border border-slate-850 border-dashed rounded-lg text-slate-500">
          <ImageIcon className="w-12 h-12 stroke-[1] text-slate-600 mb-2" />
          <p className="text-sm font-semibold text-slate-400">No media assets found</p>
          <p className="text-xs opacity-75 mt-1 text-slate-500">
            {selectedTags.length > 0
              ? `No asset matches all selected tags: ${selectedTags.map(t => `#${t}`).join(' AND ')}`
              : activeSearch
              ? 'Try revising your natural language search terms.'
              : 'Upload assets in S3 Filemanager to index them.'}
          </p>
          {selectedTags.length > 0 && (
            <button
              onClick={clearTagFilters}
              className="mt-3 px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-xs transition"
            >
              Clear tag filters
            </button>
          )}
        </div>
      ) : viewMode === 'grid' ? (
        /* Grid Layout Catalog */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {sortedList.map((file) => {
            const isImage = file.content_type.toLowerCase().startsWith('image/');
            const isVideo = file.content_type.toLowerCase().startsWith('video/');
            const isAudio = file.content_type.toLowerCase().startsWith('audio/');
            const isEditingTag = addingTagAssetId === file.id;

            return (
              <div
                key={file.id}
                className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden hover:border-slate-700 transition flex flex-col group"
              >
                {/* Media Preview Card Area */}
                <div className="h-44 w-full bg-slate-950 relative flex items-center justify-center overflow-hidden border-b border-slate-850">
                  {/* Batch Select Checkbox (#106) */}
                  <div className="absolute top-2.5 left-2.5 z-20">
                    <input
                      type="checkbox"
                      checked={selectedAssetIds.has(file.id)}
                      onChange={() => handleToggleSelectAsset(file.id)}
                      className="w-4 h-4 rounded bg-slate-900/90 border-slate-600 text-sky-600 focus:ring-sky-500 cursor-pointer shadow-md"
                      title={`Select ${file.title}`}
                    />
                  </div>
                  {isImage && file.url ? (
                    <img
                      src={file.url}
                      alt={file.title}
                      className="w-full h-full object-cover group-hover:scale-105 transition duration-300"
                    />
                  ) : isVideo && file.url ? (
                    <video
                      src={file.url}
                      className="w-full h-full object-cover"
                      controls
                      preload="metadata"
                    />
                  ) : isAudio && file.url ? (
                    <div className="w-full h-full flex flex-col justify-end p-3 relative bg-slate-950/80">
                      <div className="absolute inset-0 flex items-center justify-center opacity-10">
                        <Volume2 className="w-24 h-24 text-sky-400" />
                      </div>
                      <div className="z-10 w-full">
                        <audio src={file.url} className="w-full h-8" controls preload="none" />
                      </div>
                    </div>
                  ) : (
                    <div className="flex flex-col items-center gap-2 text-slate-600">
                      <File className="w-10 h-10" />
                      <span className="text-xs font-mono">Undefined Format</span>
                    </div>
                  )}

                  {/* Badges Overlay */}
                  <div className="absolute top-2.5 left-2.5 flex items-center gap-1.5 z-10 pointer-events-none">
                    {isVideo && (
                      <span className="bg-indigo-900/90 border border-indigo-850 text-indigo-300 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 shadow">
                        <Video className="w-3 h-3" /> Video
                      </span>
                    )}
                    {isAudio && (
                      <span className="bg-amber-900/90 border border-amber-850 text-amber-300 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 shadow">
                        <Volume2 className="w-3 h-3" /> Audio
                      </span>
                    )}
                    {isImage && (
                      <span className="bg-emerald-900/90 border border-emerald-850 text-emerald-300 px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 shadow">
                        <ImageIcon className="w-3 h-3" /> Image
                      </span>
                    )}
                  </div>
                </div>

                {/* Metadata & Title Card Info */}
                <div className="p-4 flex-1 flex flex-col justify-between space-y-3">
                  <div className="space-y-2">
                    <h3 className="font-semibold text-slate-200 text-sm line-clamp-1" title={file.title}>
                      {file.title}
                    </h3>
                    <p className="text-[10px] text-slate-500 font-mono break-all leading-normal">
                      Path: {file.file_path}
                    </p>
                  </div>

                  {/* Inline Tag Chips & Add Tag (#105) */}
                  <div className="pt-2 border-t border-slate-850 space-y-1.5">
                    <div className="flex items-center justify-between text-[11px] text-slate-400">
                      <span className="flex items-center gap-1">
                        <TagIcon className="w-3 h-3 text-sky-400" />
                        Tags
                      </span>
                      {!isEditingTag && (
                        <button
                          onClick={() => {
                            setAddingTagAssetId(file.id);
                            setNewTagName('');
                            setTagError(null);
                          }}
                          className="text-sky-400 hover:text-sky-300 text-[10px] flex items-center gap-0.5 font-medium transition"
                        >
                          <Plus className="w-3 h-3" /> Add tag
                        </button>
                      )}
                    </div>

                    <div className="flex flex-wrap items-center gap-1 min-h-[24px]">
                      {(file.tags || []).map((t) => (
                        <span
                          key={t.id}
                          className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-800 text-sky-300 rounded text-[11px] font-medium border border-slate-700 group/tag"
                        >
                          <span>#{t.name}</span>
                          <button
                            onClick={() => handleRemoveTag(file.id, t.id)}
                            disabled={tagActionLoading === file.id}
                            className="text-slate-500 hover:text-rose-400 transition"
                            title={`Remove #${t.name}`}
                          >
                            <X className="w-2.5 h-2.5" />
                          </button>
                        </span>
                      ))}

                      {(!file.tags || file.tags.length === 0) && !isEditingTag && (
                        <span className="text-[10px] text-slate-600 italic">No tags</span>
                      )}

                      {/* Inline Input for New Tag */}
                      {isEditingTag && (
                        <div className="w-full mt-1 space-y-1">
                          <div className="flex items-center gap-1 w-full">
                            <input
                              type="text"
                              autoFocus
                              value={newTagName}
                              onChange={(e) => {
                                setNewTagName(e.target.value);
                                if (tagError) setTagError(null);
                              }}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') {
                                  e.preventDefault();
                                  handleAddTag(file.id);
                                } else if (e.key === 'Escape') {
                                  setAddingTagAssetId(null);
                                  setTagError(null);
                                }
                              }}
                              placeholder="tag name..."
                              className="flex-1 bg-slate-950 border border-sky-500 rounded px-2 py-0.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none"
                            />
                            <button
                              onClick={() => handleAddTag(file.id)}
                              disabled={tagActionLoading === file.id}
                              className="p-1 bg-sky-600 hover:bg-sky-500 text-white rounded text-xs transition"
                              title="Confirm add tag"
                            >
                              <Check className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => {
                                setAddingTagAssetId(null);
                                setTagError(null);
                              }}
                              className="p-1 bg-slate-800 hover:bg-slate-750 text-slate-400 rounded text-xs transition"
                              title="Cancel"
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                    {tagError && tagError.assetId === file.id && (
                      <p className="text-[10px] text-rose-400 font-medium">{tagError.message}</p>
                    )}
                  </div>

                  <div className="pt-3 border-t border-slate-850 flex items-center justify-between text-slate-500 text-[10px]">
                    <div className="flex items-center gap-2">
                      <span className="flex items-center gap-1" title="File Size">
                        <HardDrive className="w-3 h-3" />
                        {formatSize(file.file_size)}
                      </span>
                      {file.duration > 0 && (
                        <span className="flex items-center gap-1" title="Duration">
                          <Clock className="w-3 h-3" />
                          {formatDuration(file.duration)}
                        </span>
                      )}
                    </div>
                    {file.created_at && (
                      <span className="flex items-center gap-1" title="Created date">
                        <Calendar className="w-3 h-3" />
                        {new Date(file.created_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>

                  {file.url && (
                    <a
                      href={file.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-2 flex items-center justify-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white px-3 py-1.5 rounded-md text-xs font-semibold transition border border-slate-700"
                    >
                      <ArrowUpRight className="w-3.5 h-3.5" />
                      Access Asset Direct URL
                    </a>
                  )}

                  {/* Before/after comparison (map #58) */}
                  {(file.upscaled_assets?.length > 0 || file.source_url) && (
                    <button
                      onClick={() => {
                        if (file.upscaled_assets?.length > 0) {
                          const child = file.upscaled_assets[0];
                          setCompare({ beforeUrl: file.url, afterUrl: child.url, title: file.title });
                        } else if (file.source_url) {
                          setCompare({ beforeUrl: file.source_url, afterUrl: file.url, title: file.title });
                        }
                      }}
                      className="mt-2 flex items-center justify-center gap-1.5 bg-emerald-950/60 hover:bg-emerald-900/70 text-emerald-300 border border-emerald-900 px-3 py-1.5 rounded-md text-xs font-semibold transition"
                      title="Compare original vs upscaled"
                    >
                      <ArrowLeftRight className="w-3.5 h-3.5" />
                      Compare
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* List Layout Catalog (#105) */
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="divide-y divide-slate-800">
            {/* Table Header */}
            <div className="hidden md:grid grid-cols-12 gap-4 px-5 py-3 bg-slate-950 text-xs font-semibold text-slate-400 uppercase tracking-wider items-center">
              <div className="col-span-4 flex items-center gap-2.5">
                <input
                  type="checkbox"
                  checked={isAllItemsSelected(selectedAssetIds, sortedList.map(a => a.id))}
                  onChange={handleToggleSelectAll}
                  className="w-4 h-4 rounded bg-slate-900 border-slate-700 text-sky-600 focus:ring-sky-500 cursor-pointer"
                  title="Select all"
                />
                <span>Asset / Title</span>
              </div>
              <div className="col-span-2">Type &amp; Size</div>
              <div className="col-span-4">Tags</div>
              <div className="col-span-2 text-right">Actions</div>
            </div>

            {/* Rows */}
            {sortedList.map((file) => {
              const isImage = file.content_type.toLowerCase().startsWith('image/');
              const isVideo = file.content_type.toLowerCase().startsWith('video/');
              const isAudio = file.content_type.toLowerCase().startsWith('audio/');
              const isEditingTag = addingTagAssetId === file.id;

              return (
                <div
                  key={file.id}
                  className="grid grid-cols-1 md:grid-cols-12 items-center gap-4 px-5 py-3.5 hover:bg-slate-850/50 transition text-sm"
                >
                  {/* Col 1: Title & preview icon */}
                  <div className="col-span-4 flex items-center gap-3">
                    <input
                      type="checkbox"
                      checked={selectedAssetIds.has(file.id)}
                      onChange={() => handleToggleSelectAsset(file.id)}
                      className="w-4 h-4 rounded bg-slate-900 border-slate-700 text-sky-600 focus:ring-sky-500 cursor-pointer flex-shrink-0"
                      title={`Select ${file.title}`}
                    />
                    <div className="w-10 h-10 rounded bg-slate-950 flex-shrink-0 flex items-center justify-center overflow-hidden border border-slate-800">
                      {isImage && file.url ? (
                        <img src={file.url} alt={file.title} className="w-full h-full object-cover" />
                      ) : isVideo ? (
                        <Video className="w-5 h-5 text-indigo-400" />
                      ) : isAudio ? (
                        <Volume2 className="w-5 h-5 text-amber-400" />
                      ) : (
                        <File className="w-5 h-5 text-slate-400" />
                      )}
                    </div>
                    <div className="truncate max-w-[85%]">
                      <p className="font-medium text-slate-200 truncate" title={file.title}>
                        {file.title}
                      </p>
                      <p className="text-[10px] text-slate-500 font-mono truncate">{file.file_path}</p>
                    </div>
                  </div>

                  {/* Col 2: Type & Size */}
                  <div className="col-span-2 text-xs text-slate-400 space-y-0.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-slate-300">{formatSize(file.file_size)}</span>
                      {file.duration > 0 && (
                        <span className="text-slate-500 font-mono">({formatDuration(file.duration)})</span>
                      )}
                    </div>
                    <div className="text-[10px] text-slate-500 capitalize">
                      {isVideo ? 'Video' : isAudio ? 'Audio' : isImage ? 'Image' : 'File'}
                    </div>
                  </div>

                  {/* Col 3: Tags (with inline add/remove) */}
                  <div className="col-span-4 flex flex-wrap items-center gap-1">
                    {(file.tags || []).map((t) => (
                      <span
                        key={t.id}
                        className="inline-flex items-center gap-1 px-2 py-0.5 bg-slate-800 text-sky-300 rounded text-[11px] font-medium border border-slate-700"
                      >
                        <span>#{t.name}</span>
                        <button
                          onClick={() => handleRemoveTag(file.id, t.id)}
                          disabled={tagActionLoading === file.id}
                          className="text-slate-500 hover:text-rose-400 transition"
                          title={`Remove #${t.name}`}
                        >
                          <X className="w-2.5 h-2.5" />
                        </button>
                      </span>
                    ))}

                    {(!file.tags || file.tags.length === 0) && !isEditingTag && (
                      <span className="text-[11px] text-slate-600 italic">No tags</span>
                    )}

                    {!isEditingTag ? (
                      <button
                        onClick={() => {
                          setAddingTagAssetId(file.id);
                          setNewTagName('');
                          setTagError(null);
                        }}
                        className="p-1 text-sky-400 hover:text-sky-300 rounded text-[10px] flex items-center gap-0.5 hover:bg-slate-800 transition"
                        title="Add tag"
                      >
                        <Plus className="w-3 h-3" />
                      </button>
                    ) : (
                      <div className="space-y-1">
                        <div className="flex items-center gap-1">
                          <input
                            type="text"
                            autoFocus
                            value={newTagName}
                            onChange={(e) => {
                              setNewTagName(e.target.value);
                              if (tagError) setTagError(null);
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                e.preventDefault();
                                handleAddTag(file.id);
                              } else if (e.key === 'Escape') {
                                setAddingTagAssetId(null);
                                setTagError(null);
                              }
                            }}
                            placeholder="tag name..."
                            className="bg-slate-950 border border-sky-500 rounded px-2 py-0.5 text-xs text-slate-200 placeholder-slate-600 w-24 focus:outline-none"
                          />
                          <button
                            onClick={() => handleAddTag(file.id)}
                            disabled={tagActionLoading === file.id}
                            className="p-0.5 bg-sky-600 hover:bg-sky-500 text-white rounded text-xs transition"
                            title="Confirm"
                          >
                            <Check className="w-3 h-3" />
                          </button>
                          <button
                            onClick={() => {
                              setAddingTagAssetId(null);
                              setTagError(null);
                            }}
                            className="p-0.5 bg-slate-800 hover:bg-slate-700 text-slate-400 rounded text-xs transition"
                            title="Cancel"
                          >
                            <X className="w-3 h-3" />
                          </button>
                        </div>
                      </div>
                    )}
                    {tagError && tagError.assetId === file.id && (
                      <p className="text-[10px] text-rose-400 font-medium">{tagError.message}</p>
                    )}
                  </div>

                  {/* Col 4: Actions */}
                  <div className="col-span-2 flex items-center justify-end gap-2">
                    {file.url && (
                      <a
                        href={file.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white rounded transition"
                        title="Direct URL"
                      >
                        <ArrowUpRight className="w-3.5 h-3.5" />
                      </a>
                    )}
                    {(file.upscaled_assets?.length > 0 || file.source_url) && (
                      <button
                        onClick={() => {
                          if (file.upscaled_assets?.length > 0) {
                            const child = file.upscaled_assets[0];
                            setCompare({ beforeUrl: file.url, afterUrl: child.url, title: file.title });
                          } else if (file.source_url) {
                            setCompare({ beforeUrl: file.source_url, afterUrl: file.url, title: file.title });
                          }
                        }}
                        className="p-1.5 bg-emerald-950/60 hover:bg-emerald-900/70 text-emerald-300 border border-emerald-900 rounded transition"
                        title="Compare original vs upscaled"
                      >
                        <ArrowLeftRight className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {compare && (
        <BeforeAfterModal
          beforeUrl={compare.beforeUrl}
          afterUrl={compare.afterUrl}
          title={`Compare — ${compare.title}`}
          onClose={() => setCompare(null)}
        />
      )}
    </div>
  );
}
