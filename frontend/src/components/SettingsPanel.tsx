'use client';

import React, { useState } from 'react';
import { useStore } from '../store/useStore';
import {
  Key,
  Shield,
  HelpCircle,
  Eye,
  EyeOff,
  Cpu,
  CheckCircle2,
  Server,
  Terminal,
  ExternalLink
} from 'lucide-react';

export default function SettingsPanel() {
  const { apiKeys, setApiKeys, colabTunnel, setColabTunnel } = useStore();

  const [geminiKeyInput, setGeminiKeyInput] = useState(apiKeys.geminiKey);
  const [elevenLabsInput, setElevenLabsInput] = useState(apiKeys.elevenLabsKey);
  const [tunnelUrlInput, setTunnelUrlInput] = useState(colabTunnel.endpointUrl);
  
  const [showGemini, setShowGemini] = useState(false);
  const [showEleven, setShowEleven] = useState(false);
  const [savedKeys, setSavedKeys] = useState(false);
  const [savedTunnel, setSavedTunnel] = useState(false);

  const saveApiKeys = (e: React.FormEvent) => {
    e.preventDefault();
    setApiKeys({
      geminiKey: geminiKeyInput,
      elevenLabsKey: elevenLabsInput,
    });
    setSavedKeys(true);
    setTimeout(() => setSavedKeys(false), 3000);
  };

  const saveTunnelSettings = (e: React.FormEvent) => {
    e.preventDefault();
    setColabTunnel({
      endpointUrl: tunnelUrlInput,
    });
    setSavedTunnel(true);
    setTimeout(() => setSavedTunnel(false), 3000);
  };

  const toggleTunnelState = () => {
    const nextStatus = colabTunnel.status === 'running' ? 'disconnected' : 'running';
    setColabTunnel({ status: nextStatus });
  };

  return (
    <div className="space-y-8 animate-fadeIn max-w-4xl">
      {/* Introduction Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6">
        <h2 className="text-xl font-bold text-white flex items-center gap-2 mb-2">
          <Shield className="w-5 h-5 text-sky-400" /> System Integration Configuration
        </h2>
        <p className="text-sm text-slate-400 leading-relaxed">
          FusionClip uses commercial APIs for transcription, media analysis, and voice cloning,
          paired with Google Colab GPU notebook runners for heavy local generative model tasks (like
          Flux or SDXL image sandboxes).
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        {/* API Credentials Card */}
        <section className="bg-slate-900 border border-slate-800 rounded-lg p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2 border-b border-slate-800 pb-3 mb-5">
              <Key className="w-5 h-5 text-indigo-400" /> Commercial API Keys
            </h3>

            <form onSubmit={saveApiKeys} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-450 uppercase mb-2 tracking-wider">
                  Google Gemini API Key
                </label>
                <div className="relative">
                  <input
                    type={showGemini ? 'text' : 'password'}
                    placeholder="Enter Gemini API key..."
                    value={geminiKeyInput}
                    onChange={(e) => setGeminiKeyInput(e.target.value)}
                    className="bg-slate-950 border border-slate-700 rounded-md w-full px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 pr-10 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowGemini(!showGemini)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-500 hover:text-slate-350"
                  >
                    {showGemini ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <span className="text-[10px] text-slate-550 mt-1 block">
                  Used for multimodal video scanning, generative prompt expansions, and transcriptions.
                </span>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-450 uppercase mb-2 tracking-wider">
                  ElevenLabs API Key
                </label>
                <div className="relative">
                  <input
                    type={showEleven ? 'text' : 'password'}
                    placeholder="Enter ElevenLabs API key..."
                    value={elevenLabsInput}
                    onChange={(e) => setElevenLabsInput(e.target.value)}
                    className="bg-slate-950 border border-slate-700 rounded-md w-full px-3 py-2 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 pr-10 font-mono"
                  />
                  <button
                    type="button"
                    onClick={() => setShowEleven(!showEleven)}
                    className="absolute inset-y-0 right-0 pr-3 flex items-center text-slate-500 hover:text-slate-350"
                  >
                    {showEleven ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <span className="text-[10px] text-slate-550 mt-1 block">
                  Used for TTS synthesis, dynamic audio voice cloning samples, and sound effects overlays.
                </span>
              </div>

              <div className="pt-4 flex items-center justify-between">
                <button
                  type="submit"
                  className="bg-sky-600 hover:bg-sky-500 text-white font-semibold text-sm px-4 py-2 rounded-md shadow-sm transition active:scale-[98%]"
                >
                  Save API Keys
                </button>

                {savedKeys && (
                  <span className="text-emerald-400 text-xs flex items-center gap-1 animate-fadeIn">
                    <CheckCircle2 className="w-4 h-4" /> Saved!
                  </span>
                )}
              </div>
            </form>
          </div>

          <div className="mt-8 bg-slate-950/40 border border-slate-800 p-4 rounded-md text-xs text-slate-400 space-y-2">
            <span className="font-semibold text-slate-300 block flex items-center gap-1.5">
              <HelpCircle className="w-3.5 h-3.5 text-indigo-400" /> Sandbox Safety
            </span>
            <p>
              API keys are stored securely in local browser state storage. They never leave your
              device except to communicate with direct endpoints.
            </p>
          </div>
        </section>

        {/* Remote Colab Tunnel Card */}
        <section className="bg-slate-900 border border-slate-800 rounded-lg p-6 flex flex-col justify-between">
          <div>
            <h3 className="text-lg font-bold text-white flex items-center gap-2 border-b border-slate-800 pb-3 mb-5">
              <Cpu className="w-5 h-5 text-emerald-400" /> Remote Colab GPU Workers
            </h3>

            <div className="space-y-5">
              {/* Tunnel status switch */}
              <div className="flex items-center justify-between bg-slate-950/60 p-4 rounded-md border border-slate-800">
                <div>
                  <span className="text-xs font-semibold text-slate-400 block uppercase">
                    Tunnel Connection State
                  </span>
                  <span className="text-sm font-semibold text-slate-205 flex items-center gap-2 mt-1">
                    {colabTunnel.status === 'running' ? (
                      <>
                        <span className="w-2 h-2 rounded-full bg-emerald-500 animate-ping" />
                        Running & Connected
                      </>
                    ) : (
                      <>
                        <span className="w-2 h-2 rounded-full bg-rose-500" />
                        Disconnected
                      </>
                    )}
                  </span>
                </div>

                <button
                  type="button"
                  onClick={toggleTunnelState}
                  className={`px-3 py-1.5 text-xs font-semibold rounded-md border shadow-sm transition active:scale-[98%] ${
                    colabTunnel.status === 'running'
                      ? 'bg-rose-950/45 border-rose-800 text-rose-300 hover:bg-rose-900/60'
                      : 'bg-emerald-950/45 border-emerald-800 text-emerald-300 hover:bg-emerald-900/60'
                  }`}
                >
                  {colabTunnel.status === 'running' ? 'Disconnect' : 'Connect'}
                </button>
              </div>

              {/* Endpoint form */}
              <form onSubmit={saveTunnelSettings} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-slate-450 uppercase mb-2 tracking-wider">
                    Cloudflare / ngrok Endpoint URL
                  </label>
                  <input
                    type="url"
                    placeholder="https://xxxx-your-tunnel-endpoint.trycloudflare.com"
                    value={tunnelUrlInput}
                    onChange={(e) => setTunnelUrlInput(e.target.value)}
                    className="bg-slate-950 border border-slate-700 rounded-md w-full px-3 py-2 text-sm text-slate-105 placeholder-slate-650 focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 font-mono"
                  />
                  <span className="text-[10px] text-slate-550 mt-1 block">
                    URL of the Ngrok or Cloudflare tunnel created inside the Google Colab worker notebook.
                  </span>
                </div>

                <div className="pt-2 flex items-center justify-between">
                  <button
                    type="submit"
                    className="bg-sky-600 hover:bg-sky-500 text-white font-semibold text-sm px-4 py-2 rounded-md shadow-sm transition active:scale-[98%]"
                  >
                    Save Endpoint
                  </button>

                  {savedTunnel && (
                    <span className="text-emerald-400 text-xs flex items-center gap-1 animate-fadeIn">
                      <CheckCircle2 className="w-4 h-4" /> Saved!
                    </span>
                  )}
                </div>
              </form>
            </div>
          </div>

          <div className="mt-8 bg-slate-950/40 border border-slate-800 p-4 rounded-md text-xs text-slate-405 space-y-2">
            <span className="font-semibold text-slate-205 flex items-center gap-1.5">
              <Terminal className="w-3.5 h-3.5 text-emerald-400" /> Notebook Instructions
            </span>
            <p className="leading-relaxed">
              Launch our colab runner PyTorch book, select 'T4 GPU' runtime, run setup scripts. Paste the generated public tunnel URL above and toggle status to Running.
            </p>
            <a
              href="https://colab.research.google.com"
              target="_blank"
              rel="noopener noreferrer"
              className="text-emerald-400 hover:text-emerald-305 flex items-center gap-1 mt-1 font-medium transition"
            >
              Open Google Colab <ExternalLink className="w-3 h-3" />
            </a>
          </div>
        </section>
      </div>
    </div>
  );
}
