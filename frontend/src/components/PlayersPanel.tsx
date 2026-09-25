'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useStore } from '../store/useStore';
import type { AudioMarker } from '../utils/api';
import { 
  Play, 
  Pause, 
  Volume2, 
  VolumeX, 
  Upload,
  Captions,
  Subtitles,
  ChevronLeft, 
  ChevronRight, 
  Music, 
  Film, 
  ZoomIn, 
  ZoomOut,
  RotateCcw,
  Sliders,
  Settings,
  HelpCircle,
  Sparkles,
  Loader2
} from 'lucide-react';
import {
  validateSubtitleFile,
  convertSrtToVtt,
  parseSubtitleCues,
  normalizeTrackLabel,
  syncTextTrackModes,
} from '../utils/subtitles';
import {
  fetchAssetSubtitles,
  uploadAssetSubtitle,
  extractAssetSubtitles,
  fetchMediaCatalog,
} from '../utils/api';

/**
 * Draw (or redraw) the backend-attested markers on the waveform. Markers are
 * provenance overlays - e.g. a voice-clone reference - not user annotations, so
 * they are rebuilt from scratch on every call rather than accumulated.
 */
function applyMarkers(ws: any, markers?: AudioMarker[]) {
  if (!ws) return;
  try {
    ws.clearMarkers?.();
    (markers ?? []).forEach((m) => {
      if (typeof m?.time !== 'number') return;
      ws.addMarker({ time: m.time, label: m.label, color: '#f43f5e' });
    });
  } catch (err) {
    console.warn('Failed to render waveform markers:', err);
  }
}

export default function PlayersPanel() {
  // Audio Wavefer states
  const [audioUrl, setAudioUrl] = useState<string>('https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3');
  const [isAudioPlaying, setIsAudioPlaying] = useState<boolean>(false);
  const [audioVolume, setAudioVolume] = useState<number>(0.8);
  const [audioCurrentTime, setAudioCurrentTime] = useState<number>(0);
  const [audioDuration, setAudioDuration] = useState<number>(0);
  const [zoomLevel, setZoomLevel] = useState<number>(20);
  const [isAudioMuted, setIsAudioMuted] = useState<boolean>(false);
  const [audioPlaybackRate, setAudioPlaybackRate] = useState<number>(1.0);
  const [audioError, setAudioError] = useState<string | null>(null);

  const audioContainerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<any>(null);
  const audioBlobUrlRef = useRef<string | null>(null);
  const videoBlobUrlRef = useRef<string | null>(null);
  const subtitleBlobUrlsRef = useRef<string[]>([]);

  // Cleanup object URLs on unmount (#109)
  useEffect(() => {
    return () => {
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current);
      }
      if (videoBlobUrlRef.current) {
        URL.revokeObjectURL(videoBlobUrlRef.current);
      }
      subtitleBlobUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    };
  }, []);

  // Latest clip published by the generation panel (with voice-clone markers).
  const waveAudio = useStore((s) => s.waveAudio);
  const waveAudioRef = useRef(waveAudio);

  useEffect(() => {
    waveAudioRef.current = waveAudio;
  }, [waveAudio]);

  // Load the generated clip instead of the demo URL once one exists.
  useEffect(() => {
    if (waveAudio?.url && waveAudio.url !== audioUrl) {
      setAudioUrl(waveAudio.url);
    }
  }, [waveAudio, audioUrl]);

  // Video Custom Player states
  const [videoUrl, setVideoUrl] = useState<string>('https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4');
  const [isVideoPlaying, setIsVideoPlaying] = useState<boolean>(false);
  const [videoVolume, setVideoVolume] = useState<number>(0.8);
  const [videoCurrentTime, setVideoCurrentTime] = useState<number>(0);
  const [videoDuration, setVideoDuration] = useState<number>(0);
  const [videoMuted, setVideoMuted] = useState<boolean>(false);
  const [videoFps, setVideoFps] = useState<number>(30);
  const [videoPlaybackRate, setVideoPlaybackRate] = useState<number>(1.0);
  const [videoLoop, setVideoLoop] = useState<boolean>(false);
  const [videoError, setVideoError] = useState<string | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);

  // Subtitle track support (#46, #109)
  const [activeAssetId, setActiveAssetId] = useState<number | null>(null);
  const [libraryVideos, setLibraryVideos] = useState<{ id: number; title: string; url: string }[]>([]);
  const [subtitleTracks, setSubtitleTracks] = useState<
    { id: string; label: string; language: string; url: string; cues?: { start: number; end: number; text: string }[]; isError?: boolean }[]
  >([]);
  const [activeSubtitleId, setActiveSubtitleId] = useState<string | null>(null);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState<boolean>(false);
  const [isExtractingSubtitles, setIsExtractingSubtitles] = useState<boolean>(false);

  // Sync native HTML5 <video> textTracks modes
  useEffect(() => {
    syncTextTrackModes(videoRef.current, activeSubtitleId, subtitlesEnabled);
  }, [activeSubtitleId, subtitlesEnabled, subtitleTracks]);

  // Load catalog media assets to allow switching video in player (#109)
  useEffect(() => {
    fetchMediaCatalog()
      .then((data) => {
        if (Array.isArray(data)) {
          const videos = data
            .filter((item) => item.content_type?.toLowerCase().startsWith('video/'))
            .map((item) => ({ id: item.id, title: item.title, url: item.url }));
          setLibraryVideos(videos);
        }
      })
      .catch((err) => {
        console.warn('Failed to load media catalog for player:', err);
      });
  }, []);

  // Hand-off from the generation panel for locally generated video (#102).
  const genVideo = useStore((s) => s.genVideo);
  useEffect(() => {
    if (genVideo?.url && genVideo.url !== videoUrl) {
      setVideoUrl(genVideo.url);
    }
    // Step buttons and the frame readout must use the clip's real frame rate.
    if (genVideo?.fps && genVideo.fps !== videoFps) {
      setVideoFps(genVideo.fps);
    }
  }, [genVideo, videoUrl, videoFps]);

  // Load and destroy Wavesurfer instance
  useEffect(() => {
    let ws: any = null;
    
    const initWaveSurfer = async () => {
      try {
        setAudioError(null);
        const WaveSurfer = (await import('wavesurfer.js')).default;
        
        if (!audioContainerRef.current) return;
        
        // Clean up previous wavesurfer instances inside the container 
        audioContainerRef.current.innerHTML = '';
        
        ws = WaveSurfer.create({
          container: audioContainerRef.current,
          waveColor: '#38bdf8', // sky-400
          progressColor: '#4f46e5', // indigo-600
          cursorColor: '#f43f5e', // rose-500
          barWidth: 2,
          barGap: 3,
          height: 120,
          minPxPerSec: zoomLevel,
          normalize: true,
          fillParent: true,
        });

        wsRef.current = ws;

        ws.load(audioUrl);

        ws.on('audioprocess', () => {
          setAudioCurrentTime(ws.getCurrentTime());
        });

        ws.on('ready', () => {
          setAudioDuration(ws.getDuration());
          setAudioCurrentTime(ws.getCurrentTime());
          ws.setVolume(isAudioMuted ? 0 : audioVolume);
          ws.setPlaybackRate(audioPlaybackRate);
          applyMarkers(ws, waveAudioRef.current?.markers);
        });

        ws.on('seek', () => {
          setAudioCurrentTime(ws.getCurrentTime());
        });

        ws.on('play', () => setIsAudioPlaying(true));
        ws.on('pause', () => setIsAudioPlaying(false));
      } catch (err: any) {
        console.error('Wavesurfer initialization error:', err);
        setAudioError('Failed to initialize Audio Player. Using fallback visualizer.');
      }
    };

    initWaveSurfer();

    return () => {
      if (ws) {
        ws.destroy();
      }
    };
  }, [audioUrl]);

  // Sync zoom level
  useEffect(() => {
    if (wsRef.current) {
      wsRef.current.zoom(zoomLevel);
    }
  }, [zoomLevel]);

  // Keep markers in sync when a new clip arrives for an already-created player.
  useEffect(() => {
    applyMarkers(wsRef.current, waveAudio?.markers);
  }, [waveAudio, audioUrl]);

  // Sync audio volume
  useEffect(() => {
    if (wsRef.current) {
      wsRef.current.setVolume(isAudioMuted ? 0 : audioVolume);
    }
  }, [audioVolume, isAudioMuted]);

  // Sync audio playback rate
  useEffect(() => {
    if (wsRef.current) {
      wsRef.current.setPlaybackRate(audioPlaybackRate);
    }
  }, [audioPlaybackRate]);

  // Audio actions
  const handleAudioPlayPause = () => {
    if (wsRef.current) {
      wsRef.current.playPause();
    }
  };

  const handleAudioMuteToggle = () => {
    setIsAudioMuted(!isAudioMuted);
  };

  const handleAudioVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseFloat(e.target.value);
    setAudioVolume(value);
    if (value > 0 && isAudioMuted) {
      setIsAudioMuted(false);
    }
  };

  const handleAudioFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      if (audioBlobUrlRef.current) {
        URL.revokeObjectURL(audioBlobUrlRef.current);
      }
      const url = URL.createObjectURL(file);
      audioBlobUrlRef.current = url;
      setAudioUrl(url);
    }
  };

  // Video event handlers
  const handleVideoTimeUpdate = () => {
    if (videoRef.current) {
      setVideoCurrentTime(videoRef.current.currentTime);
    }
  };

  const handleVideoLoadedMetadata = () => {
    if (videoRef.current) {
      setVideoDuration(videoRef.current.duration);
    }
  };

  // Sync video audio options
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.volume = videoVolume;
      videoRef.current.muted = videoMuted;
    }
  }, [videoVolume, videoMuted]);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = videoPlaybackRate;
    }
  }, [videoPlaybackRate]);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.loop = videoLoop;
    }
  }, [videoLoop]);

  // Video Actions
  const handleVideoPlayPause = () => {
    if (videoRef.current) {
      if (isVideoPlaying) {
        videoRef.current.pause();
        setIsVideoPlaying(false);
      } else {
        videoRef.current.play().then(() => {
          setIsVideoPlaying(true);
        }).catch(err => {
          console.error(err);
          setVideoError('Unable to play video file.');
        });
      }
    }
  };

  const handleVideoScrub = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = parseFloat(e.target.value);
    if (videoRef.current) {
      videoRef.current.currentTime = time;
      setVideoCurrentTime(time);
    }
  };

  const stepFrame = (frames: number) => {
    if (videoRef.current) {
      // Pause playback when stepping frames manually
      if (isVideoPlaying) {
        videoRef.current.pause();
        setIsVideoPlaying(false);
      }
      
      const frameTime = 1 / videoFps;
      const targetTime = videoRef.current.currentTime + (frames * frameTime);
      
      // Keep boundaries
      const clampedTime = Math.max(0, Math.min(videoDuration, targetTime));
      videoRef.current.currentTime = clampedTime;
      setVideoCurrentTime(clampedTime);
    }
  };

  const handleVideoMuteToggle = () => {
    setVideoMuted(!videoMuted);
  };

  const handleVideoVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = parseFloat(e.target.value);
    setVideoVolume(value);
    if (value > 0 && videoMuted) {
      setVideoMuted(false);
    }
  };

  const handleVideoFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setVideoError(null);
      if (videoBlobUrlRef.current) {
        URL.revokeObjectURL(videoBlobUrlRef.current);
      }
      const url = URL.createObjectURL(file);
      videoBlobUrlRef.current = url;
      setVideoUrl(url);
      setActiveAssetId(null);
      setSubtitleTracks([]);
      setActiveSubtitleId(null);
      setSubtitlesEnabled(false);
      setIsVideoPlaying(false);
    }
  };

  const handleSelectLibraryVideo = async (assetIdStr: string) => {
    if (!assetIdStr) {
      setActiveAssetId(null);
      setVideoUrl('https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4');
      setSubtitleTracks([]);
      setActiveSubtitleId(null);
      setSubtitlesEnabled(false);
      return;
    }
    const assetId = parseInt(assetIdStr, 10);
    const selected = libraryVideos.find((v) => v.id === assetId);
    if (!selected) return;

    setActiveAssetId(assetId);
    setVideoUrl(selected.url);
    setIsVideoPlaying(false);
    setVideoError(null);

    // Fetch existing subtitles for this asset
    try {
      const tracks = await fetchAssetSubtitles(assetId);
      const mapped = tracks.map((t) => ({
        id: String(t.id),
        label: t.label,
        language: t.language || 'en',
        url: t.url,
      }));
      setSubtitleTracks(mapped);
      if (mapped.length > 0) {
        setActiveSubtitleId(mapped[0].id);
        setSubtitlesEnabled(true);
      } else {
        setActiveSubtitleId(null);
        setSubtitlesEnabled(false);
      }
    } catch (err) {
      console.warn('Could not fetch subtitles for asset:', err);
      setSubtitleTracks([]);
      setActiveSubtitleId(null);
      setSubtitlesEnabled(false);
    }
  };

  const handleTrackLoadError = (trackId: string) => {
    console.warn(`Subtitle track ${trackId} failed to load (e.g. 403 or CORS). Player continues.`);
    setSubtitleTracks((prev) =>
      prev.map((t) => (t.id === trackId ? { ...t, isError: true } : t))
    );
  };

  const handleExtractSubtitles = async () => {
    if (!activeAssetId) return;
    setIsExtractingSubtitles(true);
    setVideoError(null);
    try {
      const res = await extractAssetSubtitles(activeAssetId);
      if (res.tracks && res.tracks.length > 0) {
        const newTracks = res.tracks.map((t) => ({
          id: String(t.id),
          label: t.label,
          language: t.language || 'en',
          url: t.url,
        }));
        setSubtitleTracks((prev) => {
          const ids = new Set(prev.map((p) => p.id));
          return [...prev, ...newTracks.filter((nt) => !ids.has(nt.id))];
        });
        if (!activeSubtitleId && newTracks.length > 0) {
          setActiveSubtitleId(newTracks[0].id);
          setSubtitlesEnabled(true);
        }
      } else {
        setVideoError('No embedded subtitle tracks found in this video.');
      }
    } catch (err: any) {
      console.error('Failed to extract embedded subtitles:', err);
      setVideoError(err?.message || 'Failed to extract embedded subtitles');
    } finally {
      setIsExtractingSubtitles(false);
    }
  };

  // Add a subtitle track from an uploaded .srt / .vtt file
  const handleSubtitleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const validation = validateSubtitleFile(file.name, file.size);
    if (!validation.valid) {
      setVideoError(validation.error || 'Invalid subtitle file');
      return;
    }

    try {
      if (activeAssetId) {
        const uploaded = await uploadAssetSubtitle(activeAssetId, file);
        const newTrack = {
          id: String(uploaded.id),
          label: uploaded.label,
          language: uploaded.language || 'en',
          url: uploaded.url,
        };
        setSubtitleTracks((prev) => [...prev.filter((t) => t.id !== newTrack.id), newTrack]);
        setActiveSubtitleId(newTrack.id);
        setSubtitlesEnabled(true);
        setVideoError(null);
      } else {
        const reader = new FileReader();
        reader.onload = () => {
          const raw = String(reader.result || '');
          const isSrt = file.name.toLowerCase().endsWith('.srt');
          const vttContent = isSrt ? convertSrtToVtt(raw) : raw;
          const cues = parseSubtitleCues(vttContent);
          const blob = new Blob([vttContent], { type: 'text/vtt' });
          const url = URL.createObjectURL(blob);
          subtitleBlobUrlsRef.current.push(url);
          const label = normalizeTrackLabel(file.name);
          const id = `local-${Date.now()}-${label}`;
          setSubtitleTracks((prev) => [...prev, { id, label, language: 'en', url, cues }]);
          setActiveSubtitleId(id);
          setSubtitlesEnabled(true);
          setVideoError(null);
        };
        reader.onerror = () => {
          setVideoError('Failed to read subtitle file');
        };
        reader.readAsText(file);
      }
    } catch (err: any) {
      console.error('Failed to upload subtitle file:', err);
      setVideoError(err?.message || 'Failed to upload subtitle file');
    }
  };

  // Human friendly formatting
  const formatTime = (timeInSeconds: number) => {
    if (isNaN(timeInSeconds)) return '00:00';
    const minutes = Math.floor(timeInSeconds / 60);
    const seconds = Math.floor(timeInSeconds % 60);
    return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };

  const formatPreciseTime = (timeInSeconds: number) => {
    if (isNaN(timeInSeconds)) return '00:00:00.000';
    const hours = Math.floor(timeInSeconds / 3600);
    const minutes = Math.floor((timeInSeconds % 3600) / 60);
    const seconds = Math.floor(timeInSeconds % 60);
    const ms = Math.floor((timeInSeconds % 1) * 1000);
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`;
  };

  return (
    <div className="space-y-8 animate-fadeIn max-w-6xl mx-auto">
      {/* Page Heading */}
      <div className="flex flex-col md:flex-row md:items-center justify-between pb-6 border-b border-slate-900 gap-4">
        <div>
          <h2 className="text-2xl font-bold bg-gradient-to-r from-sky-400 to-indigo-500 bg-clip-text text-transparent flex items-center gap-2.5">
            <Sliders className="w-6 h-6 text-sky-400" />
            Media Analysis Players
          </h2>
          <p className="text-sm text-slate-400 mt-1">
            Frame-accurate video scrubbing and rich audio waveform timeline profiling.
          </p>
        </div>
        
        {/* API / Status badges */}
        <div className="flex items-center gap-3">
          <span className="px-3 py-1 bg-slate-900 border border-slate-800 rounded-full text-xs text-sky-400 flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
            Wavesurfer v7.x Active
          </span>
          <span className="px-3 py-1 bg-slate-900 border border-slate-800 rounded-full text-xs text-indigo-400 flex items-center gap-1.5">
            <Film className="w-3.5 h-3.5" />
            Frame-Accurate HUD
          </span>
        </div>
      </div>

      {/* Grid Container */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        
        {/* Waveform Audio Player Panel */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 flex flex-col justify-between space-y-6 hover:border-slate-700/80 transition-all duration-300">
          <div>
            <div className="flex items-center justify-between mb-4 border-b border-slate-800/60 pb-3">
              <h3 className="text-md font-bold text-slate-100 flex items-center gap-2">
                <Music className="w-4 h-4 text-sky-400" />
                Audio Waveform Profiler
              </h3>
              
              {/* Fileupload */}
              <label className="cursor-pointer px-3 py-1 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 flex items-center gap-1.5 transition-colors">
                <Upload className="w-3 h-3" />
                Upload Audio
                <input 
                  type="file" 
                  accept="audio/*" 
                  className="hidden" 
                  onChange={handleAudioFileUpload} 
                />
              </label>
            </div>

            {audioError && (
              <div className="p-3 bg-red-950/20 border border-red-900/40 text-red-400 rounded text-xs">
                {audioError}
              </div>
            )}

            {/* Wavesurfer container */}
            <div className="bg-slate-950/80 border border-slate-800/80 rounded-xl p-4 my-4 relative shadow-inner">
              <div ref={audioContainerRef} className="w-full relative z-10 min-h-[120px]" />
              
              {/* Fallback canvas message if needed */}
              {audioDuration === 0 && !audioError && (
                <div className="absolute inset-0 flex items-center justify-center bg-slate-950/50 py-10 z-0">
                  <span className="text-xs text-slate-550 animate-pulse">Loading audio waveform...</span>
                </div>
              )}

              {/* Clone markers reported by the local audio pipeline */}
              {waveAudio?.filename && (
                <div className="text-[10px] font-mono text-slate-400 mt-2">
                  Now profiling: {waveAudio.filename}
                </div>
              )}
              {(waveAudio?.markers?.length ?? 0) > 0 && (
                <div className="flex flex-wrap items-center gap-2 mt-2">
                  {waveAudio!.markers!.map((m, i) => (
                    <span
                      key={`${m.kind}-${m.time}-${i}`}
                      className="flex items-center gap-1.5 text-[10px] font-mono px-2 py-0.5 rounded-full border border-fuchsia-500/30 bg-fuchsia-500/10 text-fuchsia-200"
                      title={`${m.label} @ ${m.time.toFixed(2)}s`}
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-fuchsia-400" />
                      {m.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Controls Panel */}
          <div className="space-y-4 pt-2">
            {/* Timeline hud */}
            <div className="flex items-center justify-between bg-slate-950/40 px-3 py-2 rounded-lg border border-slate-800/40 text-xs font-mono">
              <div className="text-slate-400">Time: <span className="text-sky-400 font-semibold">{formatPreciseTime(audioCurrentTime)}</span></div>
              <div className="text-slate-500">Duration: <span className="text-slate-300">{formatPreciseTime(audioDuration)}</span></div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-4">
              {/* Primary play buttons */}
              <div className="flex items-center gap-2">
                <button
                  onClick={handleAudioPlayPause}
                  disabled={audioDuration === 0}
                  className={`p-3 rounded-lg text-white font-bold transition-all ${
                    isAudioPlaying 
                      ? 'bg-amber-600 hover:bg-amber-500' 
                      : 'bg-sky-600 hover:bg-sky-500 disabled:opacity-50'
                  }`}
                  title={isAudioPlaying ? 'Pause' : 'Play'}
                >
                  {isAudioPlaying ? <Pause className="w-4 h-4" /> : <Play className="w-4.5 h-4.5" />}
                </button>

                {/* Reset button */}
                <button
                  onClick={() => { if (wsRef.current) wsRef.current.setTime(0); }}
                  disabled={audioDuration === 0}
                  className="p-3 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-350 rounded-lg border border-slate-700 transition"
                  title="Reset to Start"
                >
                  <RotateCcw className="w-4 h-4" />
                </button>
              </div>

              {/* Volume sliders */}
              <div className="flex items-center gap-2 bg-slate-950/40 px-3 py-2 rounded-lg border border-slate-800/40">
                <button 
                  onClick={handleAudioMuteToggle}
                  className="text-slate-400 hover:text-slate-200 transition"
                >
                  {isAudioMuted || audioVolume === 0 ? (
                    <VolumeX className="w-4 h-4 text-rose-400" />
                  ) : (
                    <Volume2 className="w-4 h-4 text-sky-400" />
                  )}
                </button>
                <input 
                  type="range" 
                  min="0" 
                  max="1" 
                  step="0.05"
                  value={isAudioMuted ? 0 : audioVolume}
                  onChange={handleAudioVolumeChange}
                  className="w-20 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-sky-400"
                />
              </div>

              {/* Speed Controller */}
              <div className="flex items-center gap-1.5 text-xs">
                <span className="text-slate-400">Speed:</span>
                <select 
                  value={audioPlaybackRate}
                  onChange={(e) => setAudioPlaybackRate(parseFloat(e.target.value))}
                  className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-sky-500"
                >
                  <option value="0.5">0.5x</option>
                  <option value="1.0">1.0x (Normal)</option>
                  <option value="1.25">1.25x</option>
                  <option value="1.5">1.5x</option>
                  <option value="2.0">2.0x</option>
                </select>
              </div>
            </div>

            {/* Waveform Zoom Controls */}
            <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-800/40">
              <div className="flex items-center gap-1.5">
                <ZoomOut className="w-3.5 h-3.5 text-slate-550" />
                <span>Zoom Level</span>
              </div>
              <div className="flex items-center gap-2">
                <input 
                  type="range" 
                  min="10" 
                  max="200" 
                  step="5"
                  value={zoomLevel} 
                  onChange={(e) => setZoomLevel(parseInt(e.target.value))}
                  className="w-36 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-sky-400"
                />
                <span className="font-mono text-[11px] w-8 text-right text-slate-300">{zoomLevel}px/s</span>
              </div>
            </div>

          </div>
        </div>

        {/* Video Scrubber Player Panel */}
        <div className="bg-slate-900/50 border border-slate-800 rounded-xl p-6 flex flex-col justify-between space-y-6 hover:border-slate-700/80 transition-all duration-300">
          <div>
            <div className="flex flex-wrap items-center justify-between mb-4 border-b border-slate-800/60 pb-3 gap-2">
              <h3 className="text-md font-bold text-slate-100 flex items-center gap-2">
                <Film className="w-4 h-4 text-indigo-400" />
                Frame-by-Frame Video Scrubber
              </h3>
              
              <div className="flex items-center gap-2 flex-wrap">
                {/* Library video picker if videos exist in catalog */}
                {libraryVideos.length > 0 && (
                  <select
                    value={activeAssetId ? String(activeAssetId) : ''}
                    onChange={(e) => handleSelectLibraryVideo(e.target.value)}
                    className="bg-slate-800 border border-slate-700 text-xs text-slate-200 rounded px-2 py-1 focus:outline-none focus:border-indigo-500 max-w-[160px]"
                    title="Select video from library"
                  >
                    <option value="">Demo Video</option>
                    {libraryVideos.map((v) => (
                      <option key={v.id} value={String(v.id)}>
                        {v.title}
                      </option>
                    ))}
                  </select>
                )}

                {/* Extract embedded tracks button (available when library asset selected) */}
                {activeAssetId && (
                  <button
                    onClick={handleExtractSubtitles}
                    disabled={isExtractingSubtitles}
                    className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-xs text-amber-300 rounded border border-slate-700 flex items-center gap-1.5 transition-colors"
                    title="Detect and extract embedded subtitle tracks via ffmpeg"
                  >
                    {isExtractingSubtitles ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <Sparkles className="w-3 h-3 text-amber-400" />
                    )}
                    Extract Subs
                  </button>
                )}

                {/* Fileupload */}
                <label className="cursor-pointer px-3 py-1 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 flex items-center gap-1.5 transition-colors">
                  <Upload className="w-3 h-3" />
                  Upload Video
                  <input 
                    type="file" 
                    accept="video/*" 
                    className="hidden" 
                    onChange={handleVideoFileUpload} 
                  />
                </label>
                {/* Subtitle upload */}
                <label className="cursor-pointer px-3 py-1 bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 rounded border border-slate-700 flex items-center gap-1.5 transition-colors">
                  <Captions className="w-3 h-3" />
                  Upload Subtitles
                  <input
                    type="file"
                    accept=".srt,.vtt,text/vtt"
                    className="hidden"
                    onChange={handleSubtitleFileUpload}
                  />
                </label>
              </div>
            </div>

            {videoError && (
              <div className="p-3 bg-red-950/20 border border-red-900/40 text-red-400 rounded text-xs mb-2">
                {videoError}
              </div>
            )}

            {genVideo?.filename && (
              <div className="text-[10px] font-mono text-slate-400 mb-2">
                Now playing: {genVideo.filename}
              </div>
            )}

            {/* Custom Video Viewport Container */}
            <div className="bg-slate-950 rounded-xl border border-slate-800/80 overflow-hidden relative group shadow-lg aspect-video flex items-center justify-center">
              <video
                ref={videoRef}
                src={videoUrl}
                onClick={handleVideoPlayPause}
                onTimeUpdate={handleVideoTimeUpdate}
                onLoadedMetadata={handleVideoLoadedMetadata}
                className="w-full h-full object-contain cursor-pointer"
                playsInline
              >
                {subtitleTracks.map((track) => (
                  <track
                    key={track.id}
                    id={`track-${track.id}`}
                    kind="subtitles"
                    label={track.label}
                    srcLang={track.language || 'en'}
                    src={track.url}
                    default={activeSubtitleId === track.id && subtitlesEnabled}
                    onError={() => handleTrackLoadError(track.id)}
                  />
                ))}
              </video>
              
              {/* Pause overlay Indicator */}
              {!isVideoPlaying && (
                <div onClick={handleVideoPlayPause} className="absolute inset-0 flex items-center justify-center bg-slate-950/30 cursor-pointer transition-opacity group-hover:bg-slate-950/40">
                  <div className="p-4 rounded-full bg-slate-950/80 border border-slate-800/80 text-indigo-400 hover:text-indigo-300 hover:scale-105 transition">
                  <Play className="w-6 h-6 fill-indigo-400/20" />
                  </div>
                </div>
              )}
            </div>
            
            {/* Timeline Scrubber range slider */}
            <div className="mt-3 px-1">
              <input 
                type="range"
                min="0"
                max={videoDuration || 100}
                step="0.001"
                value={videoCurrentTime}
                onChange={handleVideoScrub}
                className="w-full h-2 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-500 hover:accent-indigo-400 transition"
              />
            </div>
          </div>

          {/* Controls HUD */}
          <div className="space-y-4 pt-1">
            {/* Time / Metric HUD */}
            <div className="grid grid-cols-3 bg-slate-950/40 px-3 py-2 rounded-lg border border-slate-800/40 text-[11px] font-mono gap-2 text-center text-slate-400">
              <div className="text-left">Time: <span className="text-indigo-400 font-semibold">{formatPreciseTime(videoCurrentTime)}</span></div>
              <div>Frame: <span className="text-slate-200 font-semibold">{Math.floor(videoCurrentTime * videoFps)}</span></div>
              <div className="text-right">Duration: <span className="text-slate-300">{formatTime(videoDuration)}</span></div>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-4 pt-1">
              {/* Group 1: Frame Stepping controls */}
              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => stepFrame(-10)}
                  disabled={videoDuration === 0}
                  className="px-2 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 rounded border border-slate-700 text-xs font-semibold flex items-center gap-0.5 transition"
                  title="Step -10 frames"
                >
                  -10f
                </button>
                <button
                  onClick={() => stepFrame(-1)}
                  disabled={videoDuration === 0}
                  className="p-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-indigo-400 hover:text-indigo-300 rounded border border-slate-700 transition"
                  title="Previous frame (Step -1 frame)"
                >
                  <ChevronLeft className="w-5 h-5" />
                </button>

                <button
                  onClick={handleVideoPlayPause}
                  disabled={videoDuration === 0}
                  className={`px-4 py-1.5 rounded text-white text-xs font-bold transition ${
                    isVideoPlaying 
                      ? 'bg-amber-600 hover:bg-amber-500' 
                      : 'bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50'
                  }`}
                >
                  {isVideoPlaying ? 'Pause' : 'Play'}
                </button>

                <button
                  onClick={() => stepFrame(1)}
                  disabled={videoDuration === 0}
                  className="p-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-indigo-400 hover:text-indigo-300 rounded border border-slate-700 transition"
                  title="Next frame (Step +1 frame)"
                >
                  <ChevronRight className="w-5 h-5" />
                </button>
                <button
                  onClick={() => stepFrame(10)}
                  disabled={videoDuration === 0}
                  className="px-2 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-slate-200 rounded border border-slate-700 text-xs font-semibold flex items-center gap-0.5 transition"
                  title="Step +10 frames"
                >
                  +10f
                </button>
              </div>

              {/* Group 2: Volume & Mute */}
              <div className="flex items-center gap-2 bg-slate-950/40 px-3 py-1.5 rounded border border-slate-800/40">
                <button 
                  onClick={handleVideoMuteToggle}
                  className="text-slate-400 hover:text-slate-200 transition"
                >
                  {videoMuted || videoVolume === 0 ? (
                    <VolumeX className="w-4 h-4 text-rose-400" />
                  ) : (
                    <Volume2 className="w-4 h-4 text-indigo-400" />
                  )}
                </button>
                <input 
                  type="range" 
                  min="0" 
                  max="1" 
                  step="0.05"
                  value={videoMuted ? 0 : videoVolume}
                  onChange={handleVideoVolumeChange}
                  className="w-16 h-1 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-indigo-500"
                />
              </div>
              {/* Group 3: Subtitles */}
              <div className="flex items-center gap-2 bg-slate-950/40 px-3 py-1.5 rounded border border-slate-800/40">
                <button
                  onClick={() => setSubtitlesEnabled((v) => !v)}
                  disabled={subtitleTracks.length === 0}
                  className={`p-1 rounded transition disabled:opacity-40 ${
                    subtitlesEnabled && activeSubtitleId
                      ? 'text-amber-400 hover:text-amber-300'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                  title={subtitlesEnabled ? 'Hide subtitles' : 'Show subtitles'}
                >
                  <Captions className="w-4 h-4" />
                </button>
                <select
                  value={subtitlesEnabled && activeSubtitleId ? activeSubtitleId : ''}
                  onChange={(e) => {
                    const val = e.target.value;
                    if (val) {
                      setActiveSubtitleId(val);
                      setSubtitlesEnabled(true);
                    } else {
                      setActiveSubtitleId(null);
                      setSubtitlesEnabled(false);
                    }
                  }}
                  disabled={subtitleTracks.length === 0}
                  className="bg-slate-950 border border-slate-800 rounded px-1.5 py-0.5 text-[11px] text-slate-300 focus:outline-none focus:border-amber-500 max-w-[140px]"
                  title="Select subtitle track"
                >
                  <option value="">Off</option>
                  {subtitleTracks.map((track) => (
                    <option key={track.id} value={track.id}>
                      {track.label}{track.isError ? ' (load error)' : ''}
                    </option>
                  ))}
                </select>
              </div>

              {/* Loop / Rate Options */}
              <div className="flex items-center gap-3 text-xs">
                <label className="flex items-center gap-1.5 text-slate-400 select-none cursor-pointer">
                  <input
                    type="checkbox"
                    checked={videoLoop}
                    onChange={(e) => setVideoLoop(e.target.checked)}
                    className="rounded bg-slate-950 border-slate-800 text-indigo-500 focus:ring-0 focus:ring-offset-0 cursor-pointer"
                  />
                  <span>Loop</span>
                </label>

                <select 
                  value={videoPlaybackRate}
                  onChange={(e) => setVideoPlaybackRate(parseFloat(e.target.value))}
                  className="bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-350 focus:outline-none focus:border-indigo-500"
                >
                  <option value="0.25">0.25x</option>
                  <option value="0.5">0.5x</option>
                  <option value="1.0">1.0x</option>
                  <option value="1.5">1.5x</option>
                  <option value="2.0">2.0x</option>
                </select>
              </div>

            </div>

            {/* FPS Settings */}
            <div className="flex items-center justify-between text-xs text-slate-400 pt-2 border-t border-slate-800/40">
              <div className="flex items-center gap-1.5">
                <Settings className="w-3.5 h-3.5 text-slate-550" />
                <span>FPS Standard For Frame Timings</span>
              </div>
              <div className="flex items-center gap-2">
                <select 
                  value={videoFps}
                  onChange={(e) => setVideoFps(parseInt(e.target.value))}
                  className="bg-slate-950 border border-slate-800 rounded px-2 py-0.5 text-slate-300 font-mono text-[11px] focus:outline-none focus:border-indigo-500"
                >
                  <option value="24">24 FPS (Film)</option>
                  <option value="25">25 FPS (PAL)</option>
                  <option value="29.97">29.97 FPS (NTSC)</option>
                  <option value="30">30 FPS (Standard Digital)</option>
                  <option value="60">60 FPS (High Frame Rate)</option>
                </select>
              </div>
            </div>
            
          </div>
        </div>

      </div>

      {/* Frame accuracy / audio scrubbing info card */}
      <div className="p-4 bg-slate-900/30 border border-slate-900 rounded-xl flex gap-3 text-xs text-slate-400 max-w-5xl mx-auto">
        <HelpCircle className="w-5 h-5 text-indigo-400 flex-shrink-0 mt-0.5" />
        <div className="space-y-1">
          <h4 className="font-bold text-slate-200">How to use Frame-Accurate Scrubbing and Waveform Zoom</h4>
          <p>
            For video, pause playback and click the step buttons (<span className="font-mono text-indigo-400">-10f</span>, <span className="font-mono text-indigo-400">-1f</span>, <span className="font-mono text-indigo-400">+1f</span>, <span className="font-mono text-indigo-400">+10f</span>) to advance or seek frame-by-frame. Adjusting the FPS Standard modifies the millisecond step duration accordingly (e.g. at 30 FPS, each 1-frame step is exactly 33.3 milliseconds). For audio, use the Zoom Level slider to expand the waveforms horizontally, enabling micro-second seek resolution inside dense soundwaves.
          </p>
        </div>
      </div>
    </div>
  );
}
