'use client';

import React, { useState, useEffect } from 'react';
import { 
  Search, Volume2, Video, Image as ImageIcon, File, 
  Loader2, ArrowUpRight, Calendar, HardDrive, RefreshCw, X, Clock, ArrowLeftRight
} from 'lucide-react';
import { fetchMediaCatalog, MediaAsset } from '../utils/api';
import BeforeAfterModal from './BeforeAfterModal';

export default function CatalogPanel() {
  const [query, setQuery] = useState('');
  const [activeSearch, setActiveSearch] = useState('');
  const [mediaList, setMediaList] = useState<MediaAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedFilter, setSelectedFilter] = useState<'all' | 'audio' | 'video' | 'image'>('all');
  // Before/after comparison (map #58): pairs a source asset with its upscaled output.
  const [compare, setCompare] = useState<{ beforeUrl: string; afterUrl: string; title: string } | null>(null);

  const loadCatalog = async (searchQuery = '') => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchMediaCatalog(searchQuery);
      setMediaList(data);
      setActiveSearch(searchQuery);
    } catch (err: any) {
      console.error(err);
      setError(err.message || 'Failed to search or load catalog assets.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadCatalog();
  }, []);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadCatalog(query);
  };

  const handleClearSearch = () => {
    setQuery('');
    loadCatalog('');
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

  // Filter items
  const filteredList = mediaList.filter(item => {
    const type = item.content_type.toLowerCase();
    if (selectedFilter === 'audio') return type.startsWith('audio/');
    if (selectedFilter === 'video') return type.startsWith('video/');
    if (selectedFilter === 'image') return type.startsWith('image/');
    return true;
  });

  // Calculate totals for badges
  const counts = {
    all: mediaList.length,
    audio: mediaList.filter(item => item.content_type.toLowerCase().startsWith('audio/')).length,
    video: mediaList.filter(item => item.content_type.toLowerCase().startsWith('video/')).length,
    image: mediaList.filter(item => item.content_type.toLowerCase().startsWith('image/')).length,
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">Vector Semantic Catalog Search</h2>
        <p className="text-xs text-slate-400">
          Search your library using natural language processing fallback to semantic patterns, and filter your assets.
        </p>
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

        <button
          onClick={() => loadCatalog(activeSearch)}
          className="p-2 border border-slate-700 bg-slate-950/40 rounded text-slate-400 hover:bg-slate-800 transition text-xs flex items-center gap-1.5"
          title="Refresh catalog list"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Refresh
        </button>
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

      {/* Grid Layout Catalog */}
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
            onClick={() => loadCatalog(activeSearch)}
            className="mt-4 px-4 py-2 bg-rose-900/40 hover:bg-rose-900/60 border border-rose-800 text-slate-200 rounded text-xs transition"
          >
            Retry Query
          </button>
        </div>
      ) : filteredList.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 bg-slate-900/30 border border-slate-850 border-dashed rounded-lg text-slate-500">
          <ImageIcon className="w-12 h-12 stroke-[1] text-slate-600 mb-2" />
          <p className="text-sm font-semibold text-slate-400">No media assets found</p>
          <p className="text-xs opacity-75 mt-1 text-slate-500">
            {activeSearch ? 'Try revising your natural language search terms.' : 'Upload assets in S3 Filemanager to index them.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredList.map((file) => {
            const isImage = file.content_type.toLowerCase().startsWith('image/');
            const isVideo = file.content_type.toLowerCase().startsWith('video/');
            const isAudio = file.content_type.toLowerCase().startsWith('audio/');

            return (
              <div
                key={file.id}
                className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden hover:border-slate-700 transition flex flex-col group"
              >
                {/* Media Preview Card Area */}
                <div className="h-44 w-full bg-slate-950 relative flex items-center justify-center overflow-hidden border-b border-slate-850">
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
                <div className="p-4 flex-1 flex flex-col justify-between">
                  <div className="space-y-2">
                    <h3 className="font-semibold text-slate-200 text-sm line-clamp-1" title={file.title}>
                      {file.title}
                    </h3>
                    <p className="text-[10px] text-slate-500 font-mono break-all leading-normal">
                      Path: {file.file_path}
                    </p>
                  </div>

                  <div className="pt-4 mt-3 border-t border-slate-850 flex items-center justify-between text-slate-500 text-[10px]">
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
                      className="mt-3 flex items-center justify-center gap-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white px-3 py-1.5 rounded-md text-xs font-semibold transition border border-slate-700"
                    >
                      <ArrowUpRight className="w-3.5 h-3.5" />
                      Access Asset Direct URL
                    </a>
                  )}

                  {/* Before/after comparison (map #58) — available when this asset
                      has an upscaled output, or when it IS an upscaled output. */}
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
                      className="mt-3 flex items-center justify-center gap-1.5 bg-emerald-950/60 hover:bg-emerald-900/70 text-emerald-300 border border-emerald-900 px-3 py-1.5 rounded-md text-xs font-semibold transition"
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
