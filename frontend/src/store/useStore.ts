import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type TabType = 'library' | 'catalog' | 'generation' | 'players' | 'settings' | 'tunnels';

interface ApiKeys {
  geminiKey: string;
  elevenLabsKey: string;
}

interface ColabTunnel {
  status: 'running' | 'disconnected';
  endpointUrl: string;
}

interface AppState {
  // Navigation
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;
  
  // API Keys Config
  apiKeys: ApiKeys;
  setApiKeys: (keys: Partial<ApiKeys>) => void;
  
  // Colab Tunnel Config
  colabTunnel: ColabTunnel;
  setColabTunnel: (tunnel: Partial<ColabTunnel>) => void;
  
  // Layout
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
}

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      activeTab: 'library',
      setActiveTab: (activeTab) => set({ activeTab }),
      
      apiKeys: {
        geminiKey: '',
        elevenLabsKey: '',
      },
      setApiKeys: (keys) =>
        set((state) => ({
          apiKeys: { ...state.apiKeys, ...keys },
        })),
      
      colabTunnel: {
        status: 'disconnected',
        endpointUrl: '',
      },
      setColabTunnel: (tunnel) =>
        set((state) => ({
          colabTunnel: { ...state.colabTunnel, ...tunnel },
        })),
      
      sidebarOpen: true,
      toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
      setSidebarOpen: (sidebarOpen) => set({ sidebarOpen }),
    }),
    {
      name: 'fusionclip-settings', // persisted in localStorage
    }
  )
);
