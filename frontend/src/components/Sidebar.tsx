'use client';

import React from 'react';
import { useStore, TabType } from '../store/useStore';
import { Folder, Sparkles, Settings, Sliders, Menu, X, Search } from 'lucide-react';

export default function Sidebar() {
  const { activeTab, setActiveTab, sidebarOpen, toggleSidebar } = useStore();

const menuItems = [
  {
    id: 'library' as TabType,
    label: 'Media Library',
    icon: Folder,
    description: 'Manage S3 assets',
  },
  {
    id: 'catalog' as TabType,
    label: 'Catalog Search',
    icon: Search,
    description: 'Semantic vector queries',
  },
  {
    id: 'generation' as TabType,
    label: 'Generative AI',
    icon: Sparkles,
    description: 'Gemini & ElevenLabs',
  },
  {
    id: 'players' as TabType,
    label: 'Media Players',
    icon: Sliders,
    description: 'Scrub Waveform',
  },
  {
    id: 'settings' as TabType,
    label: 'Configuration',
    icon: Settings,
    description: 'API Keys & Tunnels',
  },
];

  return (
    <>
      {/* Mobile toggle button */}
      <button
        onClick={toggleSidebar}
        className="fixed bottom-4 right-4 z-50 p-3 bg-sky-600 hover:bg-sky-500 text-white rounded-full shadow-lg md:hidden transition-all duration-200"
        aria-label="Toggle Sidebar"
      >
        {sidebarOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
      </button>

      {/* Sidebar Container */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 bg-slate-900 border-r border-slate-800 flex flex-col transition-transform duration-300 md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Brand Header */}
        <div className="h-16 flex items-center px-6 border-b border-slate-800 bg-slate-950/40">
          <div className="flex items-center gap-2">
            <span className="p-1.5 bg-gradient-to-r from-sky-400 to-indigo-500 rounded-lg text-white font-bold text-lg leading-none">
              FC
            </span>
            <div>
              <h1 className="font-extrabold text-sm tracking-tight text-white flex items-center gap-1.5">
                FusionClip
                <span className="text-[10px] font-mono px-1.5 py-0.5 bg-slate-800 text-sky-400 rounded border border-slate-700">
                  v1.0
                </span>
              </h1>
            </div>
          </div>
        </div>

        {/* Navigation Section */}
        <nav className="flex-1 px-4 py-6 space-y-2 overflow-y-auto">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                onClick={() => {
                  setActiveTab(item.id);
                  // Close on mobile
                  if (window.innerWidth < 768) {
                    toggleSidebar();
                  }
                }}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-all duration-200 group ${
                  isActive
                    ? 'bg-sky-950/50 border border-sky-800/80 text-sky-400 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 border border-transparent'
                }`}
              >
                <Icon className={`w-5 h-5 flex-shrink-0 transition-transform group-hover:scale-105 ${
                  isActive ? 'text-sky-400' : 'text-slate-400 group-hover:text-slate-300'
                }`} />
                <div>
                  <div className={`font-semibold text-sm leading-normal ${isActive ? 'text-slate-100' : 'text-slate-350'}`}>
                    {item.label}
                  </div>
                  <div className="text-[10px] text-slate-500 truncate group-hover:text-slate-400/80">
                    {item.description}
                  </div>
                </div>
              </button>
            );
          })}
        </nav>

        {/* Sidebar Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/20 text-xs text-slate-500 text-center">
          <p>© 2026 FusionClip Team</p>
          <a
            href="https://github.com/parth5012/FusionClip"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sky-500 hover:text-sky-400 hover:underline transition mt-1 inline-block"
          >
            GitHub Project
          </a>
        </div>
      </aside>
    </>
  );
}
