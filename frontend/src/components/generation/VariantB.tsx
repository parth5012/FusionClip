'use client';

import React, { useState } from 'react';
import { useStore } from '../../store/useStore';
import {
  Send,
  Sparkles,
  FileText,
  Image as ImageIcon,
  Mic,
  Volume2,
  Wand2,
  SlidersHorizontal,
  Clock,
  Download,
  FolderPlus,
  AlertCircle,
  ExternalLink,
  Loader2,
  Play,
} from 'lucide-react';

export default function VariantB() {
  const { keyStatus, setActiveTab } = useStore();
  const [modality, setModality] = useState<'text' | 'image' | 'tts' | 'sfx' | 'voice'>('image');
  const [prompt, setPrompt] = useState('Cyberpunk street vendor making steaming noodles under neon rain');
  const [showParams, setShowParams] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [errorSimulated, setErrorSimulated] = useState(false);

  // Params
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [voice, setVoice] = useState('Rachel');
  const [duration, setDuration] = useState('5.0s');

  const [history, setHistory] = useState([
    {
      id: 1,
      modality: 'tts',
      title: 'Rachel - Intro Narration',
      prompt: 'Welcome back to the media synthesis suite. Initializing all neural weights.',
      output: '44.1kHz • 128kbps MP3',
      timestamp: '2 mins ago',
      latency: '1.2s',
      cost: '0.001$',
    },
    {
      id: 2,
      modality: 'text',
      title: 'Gemini 3.8 Flash - Story Synopsis',
      prompt: 'Generate 3 high-concept loglines for a sci-fi mystery podcast.',
      output: '1. In 2084, a sound engineer discovers encrypted messages in atmospheric radio noise...',
      timestamp: '15 mins ago',
      latency: '0.8s',
      cost: 'Free tier',
    },
  ]);

  const handleRun = () => {
    setIsRunning(true);
    setTimeout(() => {
      setIsRunning(false);
      setHistory((prev) => [
        {
          id: Date.now(),
          modality,
          title: `${modality.toUpperCase()} Output: ${prompt.slice(0, 30)}...`,
          prompt,
          output: modality === 'image' ? '1920x1080 PNG (SynthID)' : 'Generated output ready',
          timestamp: 'Just now',
          latency: '1.1s',
          cost: '1 credit',
        },
        ...prev,
      ]);
    }, 1400);
  };

  const isGemini = modality === 'text' || modality === 'image';
  const isElevenLabs = modality === 'tts' || modality === 'sfx' || modality === 'voice';
  const keyConfigured = isGemini ? keyStatus.gemini.configured : keyStatus.elevenlabs.configured;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="text-center space-y-1">
        <h2 className="text-2xl font-black text-white tracking-tight flex items-center justify-center gap-2">
          <Sparkles className="w-6 h-6 text-sky-400" /> Unified Command Console
        </h2>
        <p className="text-xs text-slate-400">
          Variant B: Streamlined prompt-first console with live execution feed and quick modality chips.
        </p>
      </div>

      {/* Missing Key Warning */}
      {(!keyConfigured || errorSimulated) && (
        <div className="bg-red-950/40 border border-red-800/60 rounded-xl p-3.5 flex items-center justify-between gap-3 text-red-200">
          <div className="flex items-center gap-2 text-xs">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            <span>Missing required {isGemini ? 'Gemini' : 'ElevenLabs'} credentials.</span>
          </div>
          <button
            onClick={() => setActiveTab('settings')}
            className="text-xs text-red-300 hover:text-white font-semibold underline flex items-center gap-1"
          >
            Configure in Settings <ExternalLink className="w-3 h-3" />
          </button>
        </div>
      )}

      {/* Main Command Input Box */}
      <div className="bg-slate-900 border border-slate-800 focus-within:border-sky-500 rounded-2xl p-4 shadow-xl shadow-slate-950/50 transition space-y-3">
        {/* Modality Chips */}
        <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
          <div className="flex flex-wrap gap-1.5">
            {[
              { id: 'image', label: 'Image', icon: ImageIcon },
              { id: 'text', label: 'Text', icon: FileText },
              { id: 'tts', label: 'Speech', icon: Mic },
              { id: 'sfx', label: 'SFX', icon: Volume2 },
              { id: 'voice', label: 'Voice Lab', icon: Wand2 },
            ].map((chip) => {
              const Icon = chip.icon;
              const active = modality === chip.id;
              return (
                <button
                  key={chip.id}
                  onClick={() => setModality(chip.id as any)}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-semibold transition ${
                    active
                      ? 'bg-sky-500 text-slate-950 font-bold'
                      : 'bg-slate-950 text-slate-400 hover:text-slate-200 border border-slate-800'
                  }`}
                >
                  <Icon className="w-3.5 h-3.5" />
                  <span>{chip.label}</span>
                </button>
              );
            })}
          </div>

          <button
            onClick={() => setShowParams(!showParams)}
            className={`p-1.5 rounded-lg border text-xs flex items-center gap-1 transition ${
              showParams
                ? 'bg-sky-950 border-sky-600 text-sky-400'
                : 'bg-slate-950 border-slate-800 text-slate-400 hover:text-slate-200'
            }`}
          >
            <SlidersHorizontal className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Params</span>
          </button>
        </div>

        {/* Input Textarea */}
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={3}
          placeholder={`Describe what you want to generate in ${modality.toUpperCase()}...`}
          className="w-full bg-transparent text-sm text-slate-100 placeholder-slate-600 focus:outline-none resize-none"
        />

        {/* Parameter Strip (Collapsible) */}
        {showParams && (
          <div className="pt-2 border-t border-slate-800/80 grid grid-cols-1 sm:grid-cols-3 gap-3 animate-fadeIn text-xs">
            {modality === 'image' && (
              <div>
                <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Aspect Ratio</label>
                <select
                  value={aspectRatio}
                  onChange={(e) => setAspectRatio(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200"
                >
                  <option value="16:9">16:9 Landscape</option>
                  <option value="1:1">1:1 Square</option>
                  <option value="9:16">9:16 Portrait</option>
                </select>
              </div>
            )}
            {modality === 'tts' && (
              <div>
                <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Voice</label>
                <select
                  value={voice}
                  onChange={(e) => setVoice(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200"
                >
                  <option value="Rachel">Rachel (Natural)</option>
                  <option value="Adam">Adam (Deep)</option>
                  <option value="Domi">Domi (Dynamic)</option>
                </select>
              </div>
            )}
            {modality === 'sfx' && (
              <div>
                <label className="text-[10px] text-slate-400 uppercase font-bold block mb-1">Duration</label>
                <select
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-200"
                >
                  <option value="2.5s">2.5 seconds</option>
                  <option value="5.0s">5.0 seconds</option>
                  <option value="10.0s">10.0 seconds</option>
                </select>
              </div>
            )}
            <div className="flex items-end">
              <span className="text-[11px] text-slate-500">Model: Gemini 3.8 / Eleven v2</span>
            </div>
          </div>
        )}

        {/* Action Bar */}
        <div className="flex items-center justify-between pt-2 border-t border-slate-800/60">
          <div className="flex items-center gap-2 text-[11px] text-slate-500">
            <Clock className="w-3.5 h-3.5" />
            <span>Avg latency: ~1.0s</span>
          </div>

          <button
            onClick={handleRun}
            disabled={isRunning || !prompt.trim()}
            className="px-5 py-2.5 bg-sky-500 hover:bg-sky-400 text-slate-950 font-black rounded-xl text-xs flex items-center gap-2 shadow-lg shadow-sky-500/20 disabled:opacity-50 transition"
          >
            {isRunning ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Running...</span>
              </>
            ) : (
              <>
                <Send className="w-3.5 h-3.5" />
                <span>Run Generation</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Generation Feed / History */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-xs text-slate-400 px-1">
          <span className="font-bold uppercase tracking-wider text-slate-300">Live Generation Feed</span>
          <span>{history.length} items</span>
        </div>

        <div className="space-y-3">
          {history.map((item) => (
            <div
              key={item.id}
              className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 hover:border-slate-750 transition"
            >
              <div className="space-y-1 max-w-xl">
                <div className="flex items-center gap-2">
                  <span className="text-[9px] uppercase font-bold font-mono px-2 py-0.5 rounded bg-sky-950 border border-sky-800 text-sky-400">
                    {item.modality}
                  </span>
                  <span className="text-xs font-bold text-slate-200">{item.title}</span>
                  <span className="text-[10px] text-slate-500">• {item.timestamp}</span>
                </div>
                <p className="text-xs text-slate-400 line-clamp-1">{item.prompt}</p>
                <div className="text-[11px] text-slate-500 flex items-center gap-3 pt-1">
                  <span>Latency: {item.latency}</span>
                  <span>Cost: {item.cost}</span>
                  <span className="text-emerald-400 font-mono">{item.output}</span>
                </div>
              </div>

              <div className="flex items-center gap-2 flex-shrink-0 self-end sm:self-center">
                {item.modality === 'tts' && (
                  <button className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200">
                    <Play className="w-3.5 h-3.5 fill-current" />
                  </button>
                )}
                <button className="p-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200">
                  <Download className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setActiveTab('library')}
                  className="px-3 py-1.5 rounded-lg bg-sky-500/20 hover:bg-sky-500/30 text-sky-300 border border-sky-500/40 text-xs font-semibold flex items-center gap-1"
                >
                  <FolderPlus className="w-3.5 h-3.5" /> Add to S3
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
