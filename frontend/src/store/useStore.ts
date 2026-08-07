import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type TabType = 'library' | 'catalog' | 'generation' | 'players' | 'settings' | 'tunnels';

export interface ProviderKeyStatus {
  configured: boolean;
  last4: string | null;
}

export interface KeyStatus {
  gemini: ProviderKeyStatus;
  elevenlabs: ProviderKeyStatus;
}

interface ColabTunnel {
  status: 'running' | 'disconnected';
  endpointUrl: string;
}

interface AppState {
  // Navigation
  activeTab: TabType;
  setActiveTab: (tab: TabType) => void;

  // Server-reported API key configuration state.
  // Deliberately NOT persisted: no key material may ever reach localStorage.
  keyStatus: KeyStatus;
  setKeyStatus: (status: KeyStatus) => void;

  // Colab Tunnel Config
  colabTunnel: ColabTunnel;
  setColabTunnel: (tunnel: Partial<ColabTunnel>) => void;

  // Layout
  sidebarOpen: boolean;
  toggleSidebar: () => void;
  setSidebarOpen: (open: boolean) => void;
}

export const EMPTY_KEY_STATUS: KeyStatus = {
  gemini: { configured: false, last4: null },
  elevenlabs: { configured: false, last4: null },
};

export const useStore = create<AppState>()(
  persist(
    (set) => ({
      activeTab: 'library',
      setActiveTab: (activeTab) => set({ activeTab }),

      keyStatus: EMPTY_KEY_STATUS,
      setKeyStatus: (keyStatus) => set({ keyStatus }),

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
      // Allowlist of persisted slices. keyStatus is intentionally excluded so
      // that no API key material — not even a redacted last4 — is written to
      // localStorage. API keys themselves live only in the encrypted
      // server-side store and are never held in client state at all.
      partialize: (state) => ({
        activeTab: state.activeTab,
        colabTunnel: state.colabTunnel,
        sidebarOpen: state.sidebarOpen,
      }),
      // Migration: strip any apiKeys leaked by pre-WS-1 versions. Without this,
      // partialize only filters *writes* — existing users' plaintext keys stay
      // on disk and are scrubbed only as an incidental side effect of the next
      // state mutation (which never fires when the backend is unreachable).
      version: 1,
      migrate: (persistedState: any, _version: number) => {
        if (persistedState && 'apiKeys' in persistedState) {
          const { apiKeys, ...clean } = persistedState;
          return clean;
        }
        return persistedState;
      },
    }
  )
);
