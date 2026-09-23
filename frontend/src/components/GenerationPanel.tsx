'use client';

import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import {
  generateText,
  generateAudio,
  generateImage,
  GenerateTextResponse,
  GenerateAudioResponse,
  GenerateImageResponse,
} from '../utils/api';
import {
  Sparkles,
  BrainCircuit,
  Music,
  Wand2,
  FileText,
  Image as ImageIcon,
  Mic,
  Volume2,
  Sliders,
  AlertCircle,
  ExternalLink,
  Loader2,
  CheckCircle2,
  FolderPlus,
  Cpu,
} from 'lucide-react';

type Modality = 'text' | 'image' | 'tts' | 'sfx' | 'voice' | 'local';

export default function GenerationPanel() {
  const { keyStatus, setActiveTab, colabTunnel } = useStore();
  const [activeModality, setActiveModality] = useState<Modality>('text');
  const [prompt, setPrompt] = useState('A cinematic drone shot over a cybernetic neon city at dusk');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Parameter states
  const [model, setModel] = useState('gemini-3.8-flash');
  const [aspectRatio, setAspectRatio] = useState('16:9');
  const [steps, setSteps] = useState(28);
  const [scale, setScale] = useState(7.5);
  const [voiceId, setVoiceId] = useState('21m00Tcm4TlvDq8ikWAM');
  const [duration, setDuration] = useState(5.0);

  // Result states
  const [textResult, setTextResult] = useState<GenerateTextResponse | null>(null);
  const [audioResult, setAudioResult] = useState<GenerateAudioResponse | null>(null);
  const [imageResult, setImageResult] = useState<GenerateImageResponse | null>(null);

  const missingCommercialKeys = !keyStatus.gemini.configured || !keyStatus.elevenlabs.configured;

  const isGeminiRequired = activeModality === 'text' || activeModality === 'image';
  const isElevenLabsRequired =
    activeModality === 'tts' || activeModality === 'sfx' || activeModality === 'voice';

  const currentKeyMissing =
    (isGeminiRequired && !keyStatus.gemini.configured) ||
    (isElevenLabsRequired && !keyStatus.elevenlabs.configured);

  const handleGenerate = async () => {
    if (!prompt.trim()) return;
    setIsGenerating(true);
    setError(null);

    try {
      if (activeModality === 'text') {
        const res = await generateText(prompt, model);
        setTextResult(res);
      } else if (activeModality === 'tts') {
        const res = await generateAudio(prompt, 'tts', voiceId);
        setAudioResult(res);
      } else if (activeModality === 'sfx') {
        const res = await generateAudio(prompt, 'sfx', undefined, duration);
        setAudioResult(res);
      } else if (activeModality === 'image' || activeModality === 'local') {
        const res = await generateImage(prompt, steps, scale, aspectRatio);
        setImageResult(res);
      } else if (activeModality === 'voice') {
        // Voice design preview uses ElevenLabs TTS endpoint with designated preview voice
        const res = await generateAudio(prompt, 'tts', voiceId);
        setAudioResult(res);
      }
    } catch (err: unknown) {
      console.error('Generation request failed:', err);
      const message =
        err instanceof Error ? err.message : 'Generation failed. Please verify provider credentials.';
      setError(message);
    } finally {
      setIsGenerating(false);
    }
  };

  const hasResult =
    (activeModality === 'text' && textResult) ||
    ((activeModality === 'tts' || activeModality === 'sfx' || activeModality === 'voice') && audioResult) ||
    ((activeModality === 'image' || activeModality === 'local') && imageResult);

  const getStageStatus = () => {
    if (isGenerating) return 'Status: GENERATING';
    if (hasResult) return 'Status: COMPLETED (200 OK)';
    return 'Status: IDLE';
  };

  return (
    <div className="space-y-8 animate-fadeIn max-w-5xl">
      {/* Top Banner & Header */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2 mb-2">
            <Sparkles className="w-5 h-5 text-sky-400" /> Generative AI Intelligence Suite
          </h2>
          <p className="text-sm text-slate-400 max-w-2xl">
            Unleash multimodal generative AI. FusionClip integrates Google Gemini and ElevenLabs commercial APIs alongside self-managed remote GPU tunnels for zero-inference-fee Flux / SDXL runs.
          </p>
        </div>

        {missingCommercialKeys && (
          <div className="bg-amber-950/30 border border-amber-900/50 rounded-lg p-4 text-amber-300 text-xs max-w-sm">
            <span className="font-semibold block mb-0.5 text-amber-400">API Key Configuration Required</span>
            Please configure your Google Gemini and ElevenLabs API keys in Settings to unlock real commercial generation.
          </div>
        )}
      </div>

      {/* Modality Selector Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3">
        {[
          { id: 'text', label: 'Google Gemini Text', icon: FileText, badge: 'Gemini 3.8' },
          { id: 'image', label: 'Google Gemini Image', icon: ImageIcon, badge: 'Nano Banana' },
          { id: 'tts', label: 'ElevenLabs Speech (TTS)', icon: Mic, badge: 'ElevenLabs' },
          { id: 'sfx', label: 'ElevenLabs Sound Effects', icon: Volume2, badge: 'ElevenLabs' },
          { id: 'voice', label: 'ElevenLabs Voice Design', icon: Wand2, badge: 'Voice Lab' },
          { id: 'local', label: 'Flux / SDXL Sandbox', icon: Cpu, badge: 'Colab / Local' },
        ].map((tab) => {
          const Icon = tab.icon;
          const active = activeModality === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => {
                setActiveModality(tab.id as Modality);
                setError(null);
                setTextResult(null);
                setAudioResult(null);
                setImageResult(null);
              }}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-semibold transition ${
                active
                  ? 'bg-sky-500 text-slate-950 shadow-md shadow-sky-500/20'
                  : 'bg-slate-900 text-slate-400 hover:text-slate-200 hover:bg-slate-800 border border-slate-800'
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

      {/* Missing Key Warning for Selected Modality */}
      {currentKeyMissing && (
        <div className="bg-red-950/40 border border-red-800/60 rounded-lg p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-red-200">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
            <div className="text-xs">
              <span className="font-bold text-red-300">
                {isGeminiRequired ? 'Google Gemini API Key Required' : 'ElevenLabs API Key Required'}
              </span>
              <p className="text-red-300/80 mt-0.5">
                Real API generation requires an active provider key stored in your encrypted secret vault.
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

      {/* Inline Generation Error */}
      {error && (
        <div className="bg-red-950/40 border border-red-800/60 rounded-lg p-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-red-200 animate-fadeIn">
          <div className="flex items-center gap-2.5">
            <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0" />
            <div className="text-xs">
              <span className="font-bold text-red-300">Generation Failed</span>
              <p className="text-red-300/80 mt-0.5">{error}</p>
            </div>
          </div>
          <button
            onClick={() => setActiveTab('settings')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-red-900/60 hover:bg-red-800 border border-red-700/60 rounded-md text-xs font-semibold text-white transition flex-shrink-0"
          >
            <span>Check Settings</span>
            <ExternalLink className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Two-Column Studio Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Form Inputs (5 cols) */}
        <div className="lg:col-span-5 space-y-4 bg-slate-900/80 border border-slate-800 rounded-xl p-5">
          <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
            <span className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
              <Sliders className="w-3.5 h-3.5 text-sky-400" /> Modality Inputs
            </span>
            <span className="text-[10px] text-slate-500 font-mono">
              {activeModality.toUpperCase()}
            </span>
          </div>

          {/* Prompt Input */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-300">
              {activeModality === 'voice' ? 'Preview Script (Voice Design)' : 'Prompt / Script Text'}
            </label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="Enter generation prompt..."
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500 transition resize-none"
            />
          </div>

          {/* Colab Notice for Local Sandbox */}
          {activeModality === 'local' && colabTunnel.status !== 'running' && (
            <div className="bg-slate-950/60 border border-slate-800 rounded-lg p-2.5 flex items-center justify-between text-[11px] text-slate-400">
              <span>Colab GPU disconnected. Using local fallback.</span>
              <button
                type="button"
                onClick={() => setActiveTab('tunnels')}
                className="text-sky-400 hover:text-sky-300 font-semibold underline flex items-center gap-1"
              >
                Connect Tunnel
              </button>
            </div>
          )}
          {activeModality === 'text' && (
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-300">Gemini Model</label>
              <select
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="gemini-3.8-flash">gemini-3.8-flash (Recommended)</option>
                <option value="gemini-2.5-flash">gemini-2.5-flash (Standard)</option>
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
              <div className="text-[11px] text-slate-500 bg-slate-950/50 p-2.5 rounded border border-slate-800">
                Generated via Gemini Nano Banana models. Verified SynthID watermarking applied by default.
              </div>
            </div>
          )}

          {activeModality === 'tts' && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-300">Speaker Voice</label>
              <select
                value={voiceId}
                onChange={(e) => setVoiceId(e.target.value)}
                className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-slate-200 focus:outline-none focus:border-sky-500"
              >
                <option value="21m00Tcm4TlvDq8ikWAM">Rachel (Natural & Clear)</option>
                <option value="AZnzlk1XvdvUeBnXmlld">Domi (Dynamic)</option>
                <option value="EXAVITQu4vr4xnSDxMaL">Bella (Warm)</option>
                <option value="ErXwobaYiN019PkySvjV">Antoni (Deep)</option>
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

          {activeModality === 'local' && (
            <div className="grid grid-cols-2 gap-3 pt-1">
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">Inference Steps ({steps})</label>
                <input
                  type="range"
                  min="10"
                  max="50"
                  value={steps}
                  onChange={(e) => setSteps(parseInt(e.target.value, 10))}
                  className="w-full accent-sky-500"
                />
              </div>
              <div>
                <label className="text-[10px] text-slate-400 block mb-1">CFG Scale ({scale})</label>
                <input
                  type="range"
                  min="1.0"
                  max="15.0"
                  step="0.5"
                  value={scale}
                  onChange={(e) => setScale(parseFloat(e.target.value))}
                  className="w-full accent-sky-500"
                />
              </div>
            </div>
          )}

          {/* Generate Button */}
          <button
            onClick={handleGenerate}
            disabled={isGenerating || !prompt.trim()}
            className="w-full py-3 bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-400 hover:to-blue-500 text-slate-950 font-bold rounded-lg text-xs flex items-center justify-center gap-2 shadow-lg shadow-sky-500/20 disabled:opacity-50 transition"
          >
            {isGenerating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Executing Pipeline Call...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4" />
                <span>Trigger Generation</span>
              </>
            )}
          </button>
        </div>

        {/* Right Output Stage (7 cols) */}
        <div className="lg:col-span-7 flex flex-col justify-between bg-slate-900/50 border border-slate-800 rounded-xl p-5 min-h-[420px]">
          <div>
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <span className="text-xs font-bold text-slate-200 uppercase tracking-wider">
                Output Stage & Preview
              </span>
              <span className="text-[10px] font-mono text-slate-500">
                {getStageStatus()}
              </span>
            </div>

            <div className="mt-6 flex flex-col items-center justify-center">
              {!isGenerating && !hasResult && (
                <div className="text-center py-16 space-y-3">
                  <div className="w-12 h-12 rounded-full bg-slate-800/80 flex items-center justify-center mx-auto text-slate-500 border border-slate-700">
                    <Sparkles className="w-6 h-6" />
                  </div>
                  <h4 className="text-sm font-semibold text-slate-300">Ready to Generate</h4>
                  <p className="text-xs text-slate-500 max-w-sm">
                    Enter your prompt and click Trigger Generation. Real provider output will appear here and sync to your MinIO media catalog.
                  </p>
                </div>
              )}

              {isGenerating && (
                <div className="text-center py-16 space-y-4">
                  <Loader2 className="w-10 h-10 animate-spin text-sky-400 mx-auto" />
                  <div className="space-y-1">
                    <h4 className="text-sm font-semibold text-slate-200">Executing Provider Call</h4>
                    <p className="text-xs text-slate-500">Connecting to generation engine...</p>
                  </div>
                </div>
              )}

              {!isGenerating && hasResult && (
                <div className="w-full space-y-4 animate-fadeIn">
                  <div className="flex items-center gap-2 text-xs text-emerald-400 bg-emerald-950/30 border border-emerald-800/50 px-3 py-2 rounded-lg">
                    <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
                    <span>Generation completed successfully. Asset stored in S3.</span>
                  </div>

                  {/* Text Result */}
                  {activeModality === 'text' && textResult && (
                    <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 text-xs text-slate-200 leading-relaxed font-sans max-h-64 overflow-y-auto">
                      <p className="font-semibold text-sky-400 mb-1">Gemini Storyboard Output:</p>
                      <p className="whitespace-pre-wrap">{textResult.output}</p>
                    </div>
                  )}

                  {/* Image Result */}
                  {(activeModality === 'image' || activeModality === 'local') && imageResult && (
                    <div className="rounded-lg overflow-hidden border border-slate-800 bg-slate-950 flex flex-col items-center">
                      {imageResult.url ? (
                        <div className="relative w-full">
                          <img
                            src={imageResult.url}
                            alt="Generated Output"
                            className="w-full h-auto max-h-72 object-contain bg-slate-950"
                          />
                          {activeModality === 'image' && !imageResult.colab && (
                            <span className="absolute bottom-2 right-2 text-[9px] font-mono bg-slate-950/80 px-2 py-0.5 rounded text-slate-400 border border-slate-800">
                              SynthID Watermarked
                            </span>
                          )}
                        </div>
                      ) : (
                        <div className="w-full h-48 bg-slate-900 flex items-center justify-center text-slate-500 text-xs">
                          {imageResult.filename}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Audio Result */}
                  {(activeModality === 'tts' || activeModality === 'sfx' || activeModality === 'voice') &&
                    audioResult && (
                      <div className="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-3">
                        <div className="flex items-center justify-between text-xs">
                          <span className="font-bold text-slate-200">{audioResult.filename}</span>
                          <span className="text-[10px] font-mono text-slate-500">{audioResult.type.toUpperCase()}</span>
                        </div>
                        {audioResult.url ? (
                          <audio controls src={audioResult.url} className="w-full" />
                        ) : (
                          <div className="text-xs text-slate-500">Audio uploaded: {audioResult.filename}</div>
                        )}
                      </div>
                    )}
                </div>
              )}
            </div>
          </div>

          {/* Action Footer */}
          {!isGenerating && hasResult && (
            <div className="border-t border-slate-800 pt-4 flex items-center justify-end gap-3 mt-4">
              <button
                onClick={() => setActiveTab('library')}
                className="px-4 py-2 bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs font-bold rounded-lg flex items-center gap-1.5 shadow-md shadow-sky-500/20 transition"
              >
                <FolderPlus className="w-3.5 h-3.5" />
                <span>View in S3 Library</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Feature Capabilities Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 pt-4 border-t border-slate-800/60">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-2">
          <div className="p-2 rounded-lg border w-fit text-indigo-400 border-indigo-950 bg-indigo-950/20">
            <BrainCircuit className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-white">Google Gemini</h3>
          <p className="text-xs text-slate-400">
            High-reasoning text generation, Nano Banana native image synthesis, and multimodal analysis.
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-2">
          <div className="p-2 rounded-lg border w-fit text-amber-400 border-amber-950 bg-amber-950/20">
            <Music className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-white">ElevenLabs</h3>
          <p className="text-xs text-slate-400">
            Natural speech synthesis, dynamic sound effect generation, and Instant Voice Cloning (IVC).
          </p>
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-2">
          <div className="p-2 rounded-lg border w-fit text-emerald-400 border-emerald-950 bg-emerald-950/20">
            <Wand2 className="w-5 h-5" />
          </div>
          <h3 className="text-sm font-bold text-white">Flux / SDXL Sandbox</h3>
          <p className="text-xs text-slate-400">
            Local offline text-to-image pipelines with Google Colab remote GPU acceleration.
          </p>
        </div>
      </div>
    </div>
  );
}
