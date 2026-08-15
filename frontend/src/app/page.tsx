'use client';

import React from 'react';
import Sidebar from '../components/Sidebar';
import Header from '../components/Header';
import FileManager from '../components/FileManager';
import CatalogPanel from '../components/CatalogPanel';
import GenerationPanel from '../components/GenerationPanel';
import UpscalerPanel from '../components/UpscalerPanel';
import SettingsPanel from '../components/SettingsPanel';
import PlayersPanel from '../components/PlayersPanel';
import MonitorPanel from '../components/MonitorPanel';
import { useStore } from '../store/useStore';

export default function Home() {
  const { activeTab, sidebarOpen } = useStore();

  const renderContent = () => {
    switch (activeTab) {
      case 'library':
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-bold text-slate-100">Local S3 Filemanager</h2>
              <p className="text-xs text-slate-400">
                Manage uploaded assets, browse directory hierarchy, launch background workflows.
              </p>
            </div>
            <FileManager />
          </div>
        );
      case 'catalog':
        return <CatalogPanel />;
      case 'generation':
        return <GenerationPanel />;
      case 'upscaler':
        return <UpscalerPanel />;
      case 'players':
        return <PlayersPanel />;
      case 'settings':
      case 'tunnels':
        return <SettingsPanel />;
      case 'monitor':
        return <MonitorPanel />;
      default:
        return <FileManager />;
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex">
      {/* Sidebar Navigation */}
      <Sidebar />

      {/* Main Panel Content Area */}
      <div
        className={`flex-1 flex flex-col min-h-screen transition-all duration-300 ${
          sidebarOpen ? 'md:pl-64' : 'pl-0'
        }`}
      >
        {/* Header bar controls / statuses */}
        <Header />

        {/* Dynamic View Panel Container */}
        <main className="flex-1 overflow-y-auto px-4 py-8 sm:px-6 lg:px-8 max-w-7xl w-full mx-auto">
          {renderContent()}
        </main>

        {/* Global Footer */}
        <footer className="py-6 text-center text-xs text-slate-650 border-t border-slate-900 bg-slate-950/20">
          <p>FusionClip open-source multimedia dashboard. All rights reserved © 2026.</p>
        </footer>
      </div>
    </div>
  );
}
