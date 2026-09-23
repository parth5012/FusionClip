'use client';

import React, { useState } from 'react';
import { useStore } from '../../store/useStore';
import {
  FileText,
  Image as ImageIcon,
  Mic,
  Volume2,
  Sparkles,
  Sliders,
  Play,
  Download,
  AlertCircle,
  ExternalLink,
  Loader2,
  CheckCircle2,
  Wand2,
} from 'lucide-react';

export default function VariantA() {
  const { keyStatus, setActiveTab } = useStore();
  const [activeModality, setActiveModality] = useState<'text' | 'image' | 'tts' | 'sfx' | 'voice'>('text');
  const [prompt, setPrompt] = useState('A cinematic sunset over a neon cyber city, reflections in wet asphalt');
  const [isGenerating, setIsGenerating] = useState(false);
  const [generationDone, setGenerationDone] = useState(false);
  const [errorSimulated, setErrorSimulated] = useState(false);

  // Parameters
  const [model, setModel] = useState('gemini-3.8-flash');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [voiceId, setVoiceId] = useState('21m00Tcm4TlvDq8ikWAM');
  const [duration, setDuration] = useState(5.0);

  const isGeminiRequired = activeModality === 'text' || activeModality === 'image';
  const isElevenLabsRequired = activeModality === 'tts' || activeModality === 'sfx' || activeModality === 'voice';

  const keyConfigured = isGeminiRequired
    ? keyStatus.gemini.configured
    : keyStatus.elevenlabs.configured;

  const handleGenerate = () => {
    setIsGenerating(true);
    setGenerationDone(false);
    setTimeout(() => {
      setIsGenerating(false);
      setGenerationDone(true);
    }, 1500);
  };

  return (
    <div className="space-y-6">
      {/* Top Banner & Modality Tabs */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-sky-400" /> Generation Studio
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Variant A: Focused Tabbed Studio layout with split controls and live preview stage.
          </p>
        </div>

        {/* Latency & Cost Badge */}
        <div className="flex items-center gap-2 text-xs bg-slate-900 border border-slate-800 px-3 py-1.5 rounded-lg text-slate-300">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>Est. Latency: ~1.2s</span>
          <span className="text-slate-600">|</span>
          <span className="text-sky-400">Est. Cost: 1 credit / 0.002$</span>
        </div>
      </div>

      {/* Modality Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {[
          { id: 'text', label: 'Gemini Text', icon: FileText, badge: 'Gemini 3.8' },
          { id: 'image', label: 'Nano Banana Image', icon: ImageIcon, badge: 'Gemini 3.1' },
          { id: 'tts', label: 'Speech (TTS)', icon: Mic, badge: 'ElevenLabs' },
          { id: 'sfx', label: 'Sound Effects (SFX)', icon: Volume2, badge: 'ElevenLabs' },
          { id: 'voice', label: 'Voice Design & Clone', icon: Wand2, badge: 'ElevenLabs' },
        ].map((tab) => {
          const Icon = tab.icon;
          const active = activeModality === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setActiveModality(tab.id as any);
                setGenerationDone(false);
              }}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition ${
                active
                  ? 'bg-sky-500 text-slate-950 shadow-md shadow-sky-500/20'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-850 border border-slate-800'
              }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              <span
                className={`text-[9px] px-1.5 py-0.5 rounded font-mono ${
                  active ? 'bg-sky-600/30 text-slate-950 font-bold' : 'bg-slate-800 text-slate-400'
                }`}
              >
                {tab.badge}
              </span>
            </button>
          );
        })}
      </div>

      {/* Key Missing / Error Warning Banner */}
      {(!keyConfigured || errorSimulated) && (
        <div className="bg-red-950/40 border border-red-800/60 rounded-lg p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-red-200">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
            <div className="text-xs">
              <span className="font-bold text-red-300">
                {isGeminiRequired ? 'Gemini API Key Required' : 'ElevenLabs API Key Required'}
              </span>
              <p className="text-red-300/80 mt-0.5">
                Real API generation requires an active provider key. Direct mock fallbacks are disabled for integrity.
              </p>
            </div>
          </div>
          <button
            onClick={() => setActiveTab('settings')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-900/60 hover:bg-red-800 border border-red-700/60 rounded-md text-xs font-semibold text-white transition flex-shrink-0"
          >
            <span>Configure in Settings</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Two-Column Studio Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Form & Controls (5 cols) */}
        <div className="lg:col-span-5 space-y-4 bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
            <span className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-sky-400" /> Inputs & Parameters
            </span>
            <button
              onClick={() => setErrorSimulated(!errorSimulated)}
              className="text-[10px] text-slate-500 hover:text-slate-300 underline"
            >
              {errorSimulated ? 'Clear Error Demo' : 'Simulate Key Error'}
            </button>
          </div>

          {/* Prompt Box */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-300">
              {activeModality === 'voice' ? 'Voice Description / Persona' : 'Prompt / Text Content'}
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition resize-none"
              placeholder="Enter detailed prompt..."
            />
          </div>

          {/* Contextual Param Controls */}
          {activeModality === 'text' && (
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-300">Model Selector</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="gemini-3.8-flash">gemini-3.8-flash (Recommended, Low Latency)</option>
                <option value="gemini-2.5-flash">gemini-2.5-flash (Standard)</option>
                <option value="gemini-3-pro-preview">gemini-3-pro-preview (Deep Reasoning)</option>
              </select>
            </div>
          )}

          {activeModality === 'image' && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <label className="text-xs font-medium text-slate-300">Aspect Ratio</label>
                <div className="grid grid-cols-3 gap-2">
                  {['16:9', '1:1', '9:16'].map((ratio) => (
                    <button
                      key={ratio}
                      type="button"
                      onClick={() => setAspectRatio(ratio)}
                      className={`py-1.5 text-xs font-medium rounded border ${
                        aspectRatio === ratio
                          ? 'bg-sky-500/20 border-sky-500 text-sky-300 font-bold'
                          : 'bg-slate-950 border-slate-800 text-slate-400 hover:border-slate-700'
                      }`}
                    >
                      {ratio}
                    </button>
                  ))}
                </div>
              </div>
              <div className="text-[11px] text-slate-500 bg-slate-950/50 p-2.5 rounded border border-slate-850">
                Generated via Gemini Nano Banana models. Every output is automatically watermarked with Google SynthID.
              </div>
            </div>
          )}

          {(activeModality === 'tts' || activeModality === 'sfx') && (
            <div className="space-y-3">
              {activeModality === 'tts' && (
                <div className="space-y-1.5">
                  <label className="text-xs font-medium text-slate-300">Speaker Voice</label>
                  <select
                    value={voiceId}
                    onChange={(e) => setVoiceId(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
                  >
                    <option value="21m00Tcm4TlvDq8ikWAM">Rachel (Calm & Natural)</option>
                    <option value="AZnzlk1XvdvUeBnXmlld">Domi (Energetic Narration)</option>
                    <option value="EXAVITQu4vr4xnSDxMaL">Bella (Warm & Expressive)</option>
                    <option value="ErXwobaYiN019PkySvjV">Antoni (Deep & Cinematic)</option>
                  </select>
                </div>
              )}
              {activeModality === 'sfx' && (
                <div className="space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-300 font-medium">Duration</span>
                    <span className="font-mono text-sky-400">{duration.toFixed(1)}s</span>
                  </div>
                  <input
                    type="range"
                    min="0.5"
                    max="20.0"
                    step="0.5"
                    value={duration}
                    onChange={(e) => setDuration(parseFloat(e.target.value))}
                    className="w-full accent-sky-500"
                  />
                </div>
              )}
            </div>
          )}

          {activeModality === 'voice' && (
            <div className="space-y-3">
              <div className="text-xs text-slate-400 bg-slate-950/60 p-3 rounded-lg border border-slate-850 space-y-2">
                <span className="font-bold text-slate-200 block">Instant Voice Cloning (IVC)</span>
                <p className="text-[11px] text-slate-500">
                  Upload a 1–2 minute clean vocal sample WAV/MP3 to register a high-fidelity synthetic voice clone.
                </p>
                <div className="border border-dashed border-slate-750 hover:border-slate-600 rounded p-4 text-center cursor-pointer bg-slate-900/50">
                  <span className="text-[11px] text-sky-400 block font-medium">Drag and drop audio sample or browse</span>
                  <span className="text-[9px] text-slate-500">MP3 or WAV, max 10MB</span>
                </div>
              </div>
            </div>
          )}

          {/* Action Button */}
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !prompt.trim()}
            className="w-full py-3 bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-slate-950 font-bold rounded-lg text-xs flex items-center justify-center gap-2 shadow-lg shadow-sky-500/20 disabled:opacity-50 transition"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Generating with Provider...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>Generate {activeModality.toUpperCase()}</span>
              </>
            )}
          </button>
        </div>

        {/* Right Column: Live Output / Preview Stage (7 cols) */}
        <div className="lg:col-span-7 flex flex-col justify-between bg-slate-900/50 border border-slate-800 rounded-xl p-5 min-h-[420px]">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                Stage Preview & Result
              </span>
              <span className="text-[10px] font-mono text-slate-500">
                {generationDone ? 'Status: COMPLETED (200 OK)' : 'Status: IDLE'}
              </span>
            </div>

            <div className="mt-6 flex flex-col items-center justify-center">
              {!isGenerating && !generationDone && (
                <div className="text-center py-16 space-y-3">
                  <div className="w-12 h-12 rounded-full bg-slate-800/80 flex items-center justify-center mx-auto text-slate-500 border border-slate-700">
                    <Sparkles className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-semibold text-slate-300">Ready to Generate</h4>
                  <p className="text-xs text-slate-500 max-w-sm">
                    Configure your parameters on the left and click Generate. Real media outputs will render here and auto-save into your S3 Media Library.
                  </p>
                </div>
              )}

              {isGenerating && (
                <div className="text-center py-16 space-y-4">
                  <Loader2 className="w-10 h-10 animate-spin text-sky-400 mx-auto" />
                  <div className="space-y-1">
                    <h4 className="text-sm font-semibold text-slate-200">Executing Provider Call</h4>
                    <p className="text-xs text-slate-500">
                      Sending request to {isGeminiRequired ? 'Google Gemini' : 'ElevenLabs'} API...
                    </p>
                  </div>
                </div>
              )}

              {generationDone && (
                <div className="w-full space-y-4 animate-fadeIn">
                  <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-950/30 border border-emerald-800/50 px-3 py-2 rounded-lg">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                    <span>Generation completed successfully in 1.14s. Ready for export.</span>
                  </div>

                  {activeModality === 'text' && (
                    <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-200 leading-relaxed font-sans max-h-64 overflow-y-auto">
                      <p className="font-semibold text-sky-400 mb-1">Generated Text Output:</p>
                      The twilight spilled liquid amethyst across the glass skyscrapers of Neo-Tokyo, reflecting shimmering neon holograms onto the rain-slicked asphalt below. Automated drones danced between towering spires, humming a low electric frequency that pulsed with the city's tireless artificial rhythm.
                    </div>
                  )}

                  {activeModality === 'image' && (
                    <div className="rounded-lg overflow-hidden border border-slate-800 bg-slate-950 flex flex-col items-center">
                      <div className="w-full h-56 bg-gradient-to-tr from-sky-900/40 via-purple-900/30 to-indigo-900/50 flex items-center justify-center text-slate-400 text-xs relative">
                        <ImageIcon className="w-12 h-12 text-sky-400/40 mb-2" />
                        <span className="absolute bottom-2 right-2 text-[9px] font-mono bg-slate-950/80 px-2 py-0.5 rounded text-slate-400 border border-slate-800">
                          SynthID Verified
                        </span>
                      </div>
                    </div>
                  )}

                  {(activeModality === 'tts' || activeModality === 'sfx') && (
                    <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <button className="w-10 h-10 rounded-full bg-sky-500 text-slate-950 flex items-center justify-center hover:bg-sky-400 transition shadow-md">
                            <Play className="w-4 h-4 fill-slate-950 ml-0.5" />
                          </button>
                          <div>
                            <span className="text-xs font-bold text-slate-200 block">
                              {activeModality === 'tts' ? 'Rachel_Speech_01.mp3' : 'Braam_Impact_01.mp3'}
                            </span>
                            <span className="text-[10px] text-slate-500 font-mono">
                              44.1kHz • 128kbps MP3 • 00:04.8
                            </span>
                          </div>
                        </div>
                      </div>
                      <div className="h-8 bg-slate-900 rounded border border-slate-800 flex items-center px-2">
                        <div className="w-full h-2 bg-slate-800 rounded-full overflow-hidden">
                          <div className="w-1/3 h-full bg-sky-500 rounded-full" />
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Action Footer */}
          {generationDone && (
            <div className="border-t border-slate-800 pt-4 flex items-center justify-end gap-3 mt-4">
              <button className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg flex items-center gap-1.5 transition">
                <Download className="w-3.5 h-3.5" /> Download File
              </button>
              <button
                onClick={() => setActiveTab('library')}
                className="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-bold rounded-lg flex items-center gap-1.5 shadow-md shadow-sky-500/20 transition"
              >
                <span>View in S3 Library</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
