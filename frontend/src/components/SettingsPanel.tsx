'use client';

import React, { useCallback, useEffect, useState } from 'react';
import { useStore } from '../store/useStore';
import { deleteSecret, fetchSecretStatus, saveSecrets, SaveSecretsPayload } from '../utils/api';
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
  Trash2,
  ExternalLink
} from 'lucide-react';

export default function SettingsPanel() {
  const { keyStatus, setKeyStatus, colabTunnel, setColabTunnel } = useStore();

  // Inputs are write-only: stored keys can never be read back from the server,
  // so these always start empty and are cleared again after a successful save.
  const [geminiKeyInput, setGeminiKeyInput] = useState('');
  const [elevenLabsInput, setElevenLabsInput] = useState('');
  const [tunnelUrlInput, setTunnelUrlInput] = useState(colabTunnel.endpointUrl);

  const [showGemini, setShowGemini] = useState(false);
  const [showEleven, setShowEleven] = useState(false);
  const [savedKeys, setSavedKeys] = useState(false);
  const [savedTunnel, setSavedTunnel] = useState(false);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [savingKeys, setSavingKeys] = useState(false);

  const refreshKeyStatus = useCallback(async () => {
    try {
      setKeyStatus(await fetchSecretStatus());
    } catch {
      /* backend unreachable — keep whatever state we already have */
    }
  }, [setKeyStatus]);

  useEffect(() => {
    refreshKeyStatus();
  }, [refreshKeyStatus]);

  const saveApiKeys = async (e: React.FormEvent) => {
    e.preventDefault();
    setKeyError(null);

    const payload: SaveSecretsPayload = {};
    if (geminiKeyInput.trim()) payload.gemini_api_key = geminiKeyInput.trim();
    if (elevenLabsInput.trim()) payload.elevenlabs_api_key = elevenLabsInput.trim();

    if (Object.keys(payload).length === 0) {
      setKeyError('Enter at least one API key before saving.');
      return;
    }

    setSavingKeys(true);
    try {
      await saveSecrets(payload);
      // Clear the plaintext out of component state immediately.
      setGeminiKeyInput('');
      setElevenLabsInput('');
      setShowGemini(false);
      setShowEleven(false);
      await refreshKeyStatus();
      setSavedKeys(true);
      setTimeout(() => setSavedKeys(false), 3000);
    } catch {
      setKeyError('Failed to save API keys. Check that the backend is reachable.');
    } finally {
      setSavingKeys(false);
    }
  };

  const removeKey = async (provider: 'gemini' | 'elevenlabs') => {
    setKeyError(null);
    try {
      await deleteSecret(provider);
      await refreshKeyStatus();
    } catch {
      setKeyError(`Failed to remove the ${provider} API key.`);
    }
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
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-xs font-semibold text-slate-450 uppercase tracking-wider">
                    Google Gemini API Key
                  </label>
                  {keyStatus.gemini.configured ? (
                    <span className="flex items-center gap-2 text-[10px]">
                      <span className="flex items-center gap-1 text-emerald-400 font-semibold">
                        <CheckCircle2 className="w-3 h-3" /> Configured
                        {keyStatus.gemini.last4 && (
                          <span className="font-mono text-slate-500">
                            ····{keyStatus.gemini.last4}
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeKey('gemini')}
                        title="Remove stored Gemini API key"
                        className="text-rose-400 hover:text-rose-300 transition"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  ) : (
                    <span className="text-[10px] text-amber-400 font-semibold">Not configured</span>
                  )}
                </div>
                <div className="relative">
                  <input
                    type={showGemini ? 'text' : 'password'}
                    placeholder="Enter Gemini API key..."
                    value={geminiKeyInput}
                    onChange={(e) => setGeminiKeyInput(e.target.value)}
                    autoComplete="off"
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
                <div className="flex items-center justify-between mb-2">
                  <label className="block text-xs font-semibold text-slate-450 uppercase tracking-wider">
                    ElevenLabs API Key
                  </label>
                  {keyStatus.elevenlabs.configured ? (
                    <span className="flex items-center gap-2 text-[10px]">
                      <span className="flex items-center gap-1 text-emerald-400 font-semibold">
                        <CheckCircle2 className="w-3 h-3" /> Configured
                        {keyStatus.elevenlabs.last4 && (
                          <span className="font-mono text-slate-500">
                            ····{keyStatus.elevenlabs.last4}
                          </span>
                        )}
                      </span>
                      <button
                        type="button"
                        onClick={() => removeKey('elevenlabs')}
                        title="Remove stored ElevenLabs API key"
                        className="text-rose-400 hover:text-rose-300 transition"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </span>
                  ) : (
                    <span className="text-[10px] text-amber-400 font-semibold">Not configured</span>
                  )}
                </div>
                <div className="relative">
                  <input
                    type={showEleven ? 'text' : 'password'}
                    placeholder="Enter ElevenLabs API key..."
                    value={elevenLabsInput}
                    onChange={(e) => setElevenLabsInput(e.target.value)}
                    autoComplete="off"
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

              {keyError && (
                <p className="text-xs text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded-md px-3 py-2">
                  {keyError}
                </p>
              )}

              <div className="pt-4 flex items-center justify-between">
                <button
                  type="submit"
                  disabled={savingKeys}
                  className="bg-sky-600 hover:bg-sky-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold text-sm px-4 py-2 rounded-md shadow-sm transition active:scale-[98%]"
                >
                  {savingKeys ? 'Saving…' : 'Save API Keys'}
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
              <HelpCircle className="w-3.5 h-3.5 text-indigo-400" /> Key Handling
            </span>
            <p>
              API keys are sent to the FusionClip backend once and stored encrypted on the server,
              where background workers can use them. They are never written to browser storage and
              are never returned to the browser again — only a “configured” flag and the last four
              characters. Clear the input and re-enter a key to rotate it.
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
