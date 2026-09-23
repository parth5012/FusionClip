'use client';

import React, { useState } from 'react';
import { useStore } from '../../store/useStore';
import {
  Layers,
  ChevronDown,
  ChevronRight,
  Brain,
  Volume2,
  Mic,
  Sliders,
  CheckCircle2,
  AlertTriangle,
  Play,
  ExternalLink,
  Sparkles,
  Maximize2,
  Share2,
  Database,
} from 'lucide-react';

export default function VariantC() {
  const { keyStatus, setActiveTab } = useStore();
  const [expandedSection, setExpandedSection] = useState<'gemini' | 'elevenlabs' | 'voice'>('gemini');
  const [selectedTool, setSelectedTool] = useState<string>('gemini-image');
  const [prompt, setPrompt] = useState('Cyberpunk mechanical bird with iridescent gold plumage');

  return (
    <div className="space-y-6">
      {/* Top Banner */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Layers className="w-5 h-5 text-sky-400" /> Multi-Pane AI Workspace
          </h2>
          <p className="text-xs text-slate-400">
            Variant C: Modular node & capability drawer with inspection canvas and batch asset routing.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-400">Active Pipeline:</span>
          <span className="text-xs font-mono font-bold text-sky-400 bg-sky-950 border border-sky-800 px-2 py-0.5 rounded">
            {selectedTool}
          </span>
        </div>
      </div>

      {/* Main Grid: 4 cols Drawer + 8 cols Inspector Stage */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        {/* Left Capability Drawer */}
        <div className="lg:col-span-4 space-y-3">
          {/* Group 1: Google Gemini */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <button
              onClick={() => setExpandedSection(expandedSection === 'gemini' ? ('' as any) : 'gemini')}
              className="w-full p-3.5 flex items-center justify-between text-left hover:bg-slate-850/60 transition"
            >
              <div className="flex items-center gap-2.5">
                <Brain className="w-4 h-4 text-indigo-400" />
                <span className="text-xs font-bold text-slate-200">Google Gemini Services</span>
              </div>
              <div className="flex items-center gap-2">
                {keyStatus.gemini.configured ? (
                  <span className="text-[9px] text-emerald-400 flex items-center gap-1 font-mono">
                    <CheckCircle2 className="w-3 h-3" /> Ready
                  </span>
                ) : (
                  <span className="text-[9px] text-amber-400 flex items-center gap-1 font-mono">
                    <AlertTriangle className="w-3 h-3" /> No Key
                  </span>
                )}
                {expandedSection === 'gemini' ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
              </div>
            </button>

            {expandedSection === 'gemini' && (
              <div className="p-3 pt-0 space-y-2 border-t border-slate-850 bg-slate-950/40">
                <button
                  onClick={() => setSelectedTool('gemini-text')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'gemini-text'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Text & Reasoning</span>
                  <span className="text-[9px] font-mono text-slate-500">v3.8 Flash</span>
                </button>
                <button
                  onClick={() => setSelectedTool('gemini-image')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'gemini-image'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Image Generation (Nano Banana)</span>
                  <span className="text-[9px] font-mono text-slate-500">v3.1 Flash Image</span>
                </button>
              </div>
            )}
          </div>

          {/* Group 2: ElevenLabs Audio */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <button
              onClick={() => setExpandedSection(expandedSection === 'elevenlabs' ? ('' as any) : 'elevenlabs')}
              className="w-full p-3.5 flex items-center justify-between text-left hover:bg-slate-850/60 transition"
            >
              <div className="flex items-center gap-2.5">
                <Volume2 className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-bold text-slate-200">ElevenLabs Audio Suite</span>
              </div>
              <div className="flex items-center gap-2">
                {keyStatus.elevenlabs.configured ? (
                  <span className="text-[9px] text-emerald-400 flex items-center gap-1 font-mono">
                    <CheckCircle2 className="w-3 h-3" /> Ready
                  </span>
                ) : (
                  <span className="text-[9px] text-amber-400 flex items-center gap-1 font-mono">
                    <AlertTriangle className="w-3 h-3" /> No Key
                  </span>
                )}
                {expandedSection === 'elevenlabs' ? (
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                ) : (
                  <ChevronRight className="w-4 h-4 text-slate-500" />
                )}
              </div>
            </button>

            {expandedSection === 'elevenlabs' && (
              <div className="p-3 pt-0 space-y-2 border-t border-slate-850 bg-slate-950/40">
                <button
                  onClick={() => setSelectedTool('eleven-tts')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'eleven-tts'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Text to Speech (TTS)</span>
                  <span className="text-[9px] font-mono text-slate-500">Multilingual v2</span>
                </button>
                <button
                  onClick={() => setSelectedTool('eleven-sfx')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'eleven-sfx'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Sound Effects (SFX)</span>
                  <span className="text-[9px] font-mono text-slate-500">v2 Sound</span>
                </button>
              </div>
            )}
          </div>

          {/* Group 3: Voice Lab */}
          <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
            <button
              onClick={() => setExpandedSection(expandedSection === 'voice' ? ('' as any) : 'voice')}
              className="w-full p-3.5 flex items-center justify-between text-left hover:bg-slate-850/60 transition"
            >
              <div className="flex items-center gap-2.5">
                <Mic className="w-4 h-4 text-emerald-400" />
                <span className="text-xs font-bold text-slate-200">Voice Lab & Cloning</span>
              </div>
              {expandedSection === 'voice' ? (
                <ChevronDown className="w-4 h-4 text-slate-500" />
              ) : (
                <ChevronRight className="w-4 h-4 text-slate-500" />
              )}
            </button>

            {expandedSection === 'voice' && (
              <div className="p-3 pt-0 space-y-2 border-t border-slate-850 bg-slate-950/40">
                <button
                  onClick={() => setSelectedTool('voice-design')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'voice-design'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Voice Design (Description)</span>
                  <span className="text-[9px] font-mono text-slate-500">3 slots</span>
                </button>
                <button
                  onClick={() => setSelectedTool('voice-clone')}
                  className={`w-full p-2 rounded-lg text-left text-xs transition flex items-center justify-between ${
                    selectedTool === 'voice-clone'
                      ? 'bg-sky-500/20 border border-sky-500 text-sky-300 font-semibold'
                      : 'hover:bg-slate-900 text-slate-400'
                  }`}
                >
                  <span>Instant Voice Clone (IVC)</span>
                  <span className="text-[9px] font-mono text-slate-500">Starter+ tier</span>
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Center/Right Inspector Stage */}
        <div className="lg:col-span-8 bg-slate-900/60 border border-slate-800 rounded-xl p-6 space-y-5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-3">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-200 flex items-center gap-2">
              <Sliders className="w-4 h-4 text-sky-400" /> Pipeline Configuration & Canvas
            </span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setActiveTab('settings')}
                className="text-xs text-sky-400 hover:text-sky-300 font-medium flex items-center gap-1"
              >
                <span>Credentials</span> <ExternalLink className="w-3 h-3" />
              </button>
            </div>
          </div>

          {/* Active Tool Parameters */}
          <div className="space-y-3">
            <label className="text-xs font-medium text-slate-300">Prompt / Script Payload</label>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={3}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:border-sky-500"
            />
          </div>

          {/* Preview Viewport */}
          <div className="border border-slate-800 bg-slate-950 rounded-xl p-4 min-h-[220px] flex flex-col justify-between">
            <div className="flex items-center justify-between text-xs text-slate-500 border-b border-slate-900 pb-2">
              <span>Output Artifact Stage</span>
              <div className="flex items-center gap-2">
                <Maximize2 className="w-3.5 h-3.5 cursor-pointer hover:text-slate-300" />
                <Share2 className="w-3.5 h-3.5 cursor-pointer hover:text-slate-300" />
              </div>
            </div>

            <div className="my-auto py-8 text-center space-y-2">
              <div className="w-10 h-10 rounded-full bg-slate-900 border border-slate-800 flex items-center justify-center mx-auto text-sky-400">
                <Sparkles className="w-5 h-5" />
              </div>
              <p className="text-xs text-slate-400 font-medium">Ready to dispatch to pipeline engine</p>
              <p className="text-[11px] text-slate-600">Model outputs are stream-saved directly to MinIO S3 storage.</p>
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-slate-900">
              <span className="text-[10px] text-slate-500 font-mono">Format: MP3/PNG • Provider Native</span>
              <div className="flex items-center gap-2">
                <button className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs rounded font-medium flex items-center gap-1">
                  <Database className="w-3 h-3" /> Auto-catalog
                </button>
                <button className="px-4 py-1.5 bg-sky-500 hover:bg-sky-400 text-slate-950 text-xs rounded font-bold">
                  Execute Run
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
