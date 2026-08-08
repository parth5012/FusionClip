'use client';

import React from 'react';
import { useStore } from '../store/useStore';
import { Sparkles, BrainCircuit, Music, Wand2, ArrowUpRight, Cpu } from 'lucide-react';

export default function GenerationPanel() {
  const { keyStatus } = useStore();

  const missingKeys = !keyStatus.gemini.configured || !keyStatus.elevenlabs.configured;

  const features = [
    {
      title: 'Google Gemini Multimodal Module',
      description: 'Analyze video, audio and image uploads to auto-generate content transcripts, search embeddings metadata, and context summaries.',
      icon: BrainCircuit,
      color: 'text-indigo-400 border-indigo-950 bg-indigo-950/20',
      requirements: ['Gemini API Key'],
    },
    {
      title: 'ElevenLabs Speech & Voice Cloning',
      description: 'Convert custom scripts to natural speech using preselected premium voices or generate an custom cloned voice from short audio templates.',
      icon: Music,
      color: 'text-amber-400 border-amber-955 bg-amber-955/20',
      requirements: ['ElevenLabs API Key'],
    },
    {
      title: 'Local Generative Sandbox (Flux / SDXL)',
      description: 'Execute local/offline text-to-image and image-to-image pipelines utilizing PyTorch diffusers modules.',
      icon: Wand2,
      color: 'text-emerald-450 border-emerald-950 bg-emerald-950/20',
      requirements: ['Google Colab Tunnel URL', 'GPU Workers Active'],
    },
  ];

  return (
    <div className="space-y-8 animate-fadeIn max-w-5xl">
      {/* Top Banner */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-6 flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2 mb-2">
            <Sparkles className="w-5 h-5 text-sky-400" /> Generative AI Intelligence Suite
          </h2>
          <p className="text-sm text-slate-400 max-w-2xl">
            Unleash powerful audiovisual pipelines. FusionClip integrates cloud-based commercial APIs alongside self-managed remote GPU tunnels for zero-inference-fee runs.
          </p>
        </div>
        {missingKeys && (
          <div className="bg-amber-950/30 border border-amber-900/50 rounded-lg p-4 text-amber-300 text-xs max-w-sm">
            <span className="font-semibold block mb-0.5 text-amber-400">Keys Configuration Required</span>
            Please configure your API keys in the Settings tab to authenticate commercial models.
          </div>
        )}
      </div>

      {/* Grid of features */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {features.map((feature, index) => {
          const Icon = feature.icon;
          return (
            <div
              key={index}
              className="bg-slate-909 border border-slate-800 rounded-lg p-6 flex flex-col justify-between hover:border-slate-700 transition duration-300"
            >
              <div>
                <div className={`p-2 rounded-lg border w-fit ${feature.color}`}>
                  <Icon className="w-5 h-5" />
                </div>
                <h3 className="text-base font-bold text-white mt-4 mb-2">{feature.title}</h3>
                <p className="text-xs text-slate-400 leading-relaxed">{feature.description}</p>
              </div>

              <div className="mt-6 pt-4 border-t border-slate-800/80">
                <span className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider block mb-2">
                  System Requirements
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {feature.requirements.map((req, rIdx) => (
                    <span
                      key={rIdx}
                      className="text-[9px] font-mono px-2 py-0.5 bg-slate-950 border border-slate-850 rounded text-slate-400"
                    >
                      {req}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Workflow Queue Preview banner */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-lg p-5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-slate-950/50 border border-slate-800 rounded-lg text-slate-400">
            <Cpu className="w-5 h-5 text-sky-400 animate-pulse" />
          </div>
          <div>
            <h4 className="text-sm font-bold text-slate-200">Colab Pipeline Accelerator</h4>
            <p className="text-xs text-slate-400">Connect Google Colab GPU workers to speed up background inference queues.</p>
          </div>
        </div>
        <button className="text-xs text-sky-400 hover:text-sky-300 font-semibold flex items-center gap-1 transition">
          View Pipeline Queue <ArrowUpRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
