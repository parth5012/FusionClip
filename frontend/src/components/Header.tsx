'use client';

import React from 'react';
import { useStore } from '../store/useStore';
import { Database, HardDrive, Zap, Cpu, Menu, ShieldAlert } from 'lucide-react';

export default function Header() {
  const { toggleSidebar, sidebarOpen, colabTunnel, apiKeys } = useStore();

  const missingKeys = !apiKeys.geminiKey || !apiKeys.elevenLabsKey;

  return (
    <header className="h-16 flex items-center justify-between px-6 bg-slate-900 border-b border-slate-800 sticky top-0 z-30 shadow-md">
      {/* Sidebar toggle button (hidden on desktop if sidebar is open, but lets you close/open layout) */}
      <div className="flex items-center gap-4">
        <button
          onClick={toggleSidebar}
          className="p-1 px-2 text-slate-400 hover:text-slate-200 hover:bg-slate-800 rounded transition"
          title="Toggle sidebar"
        >
          <Menu className="w-5 h-5" />
        </button>
        <span className="text-sm font-semibold text-slate-450 md:block hidden font-mono">
          Multimedia Pipeline Management Panel
        </span>
      </div>

      {/* Stack/Tunnel Status info */}
      <div className="flex items-center gap-3">
        {/* Warning if API Keys are missing */}
        {missingKeys && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-950/40 border border-amber-800/80 rounded-md text-[11px] font-medium text-amber-300 md:flex hidden">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
            <span>Setup API Keys</span>
          </div>
        )}

        {/* Postgres badge */}
        <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-950 border border-slate-800 rounded-md text-[11px] font-medium text-slate-305 transition hover:bg-slate-800/50">
          <Database className="w-3.5 h-3.5 text-indigo-400" />
          <span className="md:inline hidden">Postgres</span>
          <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
        </div>

        {/* MinIO Storage badge */}
        <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-950 border border-slate-800 rounded-md text-[11px] font-medium text-slate-305 transition hover:bg-slate-800/50">
          <HardDrive className="w-3.5 h-3.5 text-sky-450" />
          <span className="md:inline hidden">MinIO S3</span>
          <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
        </div>

        {/* Celery badge */}
        <div className="flex items-center gap-1.5 px-3 py-1 bg-slate-950 border border-slate-800 rounded-md text-[11px] font-medium text-slate-305 transition hover:bg-slate-800/50">
          <Zap className="w-3.5 h-3.5 text-amber-450" />
          <span className="md:inline hidden">Queue</span>
          <div className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
        </div>

        {/* Google Colab Tunnel status badge */}
        <div
          className={`flex items-center gap-1.5 px-3 py-1 border rounded-md text-[11px] font-medium transition cursor-pointer ${
            colabTunnel.status === 'running'
              ? 'bg-emerald-950/30 border-emerald-800/60 text-emerald-450 hover:bg-emerald-950/50'
              : 'bg-rose-950/20 border-rose-900/40 text-rose-455 hover:bg-rose-950/40'
          }`}
          title={
            colabTunnel.status === 'running'
              ? `Colab Workers Connected: ${colabTunnel.endpointUrl}`
              : 'Google Colab Tunnel Offline'
          }
        >
          <Cpu
            className={`w-3.5 h-3.5 ${
              colabTunnel.status === 'running' ? 'text-emerald-400 animate-pulse' : 'text-rose-400'
            }`}
          />
          <span>Colab Tunnels</span>
          <div
            className={`w-1.5 h-1.5 rounded-full ${
              colabTunnel.status === 'running' ? 'bg-emerald-500 animate-ping' : 'bg-rose-500'
            }`}
          />
        </div>
      </div>
    </header>
  );
}
