import { create } from 'zustand';
import type { Project, Message, Credits, PCBStatus } from '@layrix/types';

interface AppState {
  // Projets
  projects: Project[];
  projectsLoading: boolean;
  selectedProjectId: string | null;

  // Messages du chat (par projet)
  messagesByProject: Record<string, Message[]>;

  // Crédits
  credits: Credits | null;

  // Agent
  isAgentRunning: boolean;
  agentStep: 'SCHEMA' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | null;

  // Actions
  fetchProjects: () => Promise<void>;
  fetchCredits: () => Promise<void>;
  setSelectedProjectId: (id: string | null) => void;
  addProject: (project: Project) => void;
  updateProjectStatus: (id: string, status: PCBStatus) => void;
  addMessage: (projectId: string, message: Message) => void;
  setAgentRunning: (running: boolean, step?: AppState['agentStep']) => void;
  deductCredits: (amount: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  projects: [],
  projectsLoading: false,
  selectedProjectId: null,
  messagesByProject: {},
  credits: null,
  isAgentRunning: false,
  agentStep: null,

  fetchCredits: async () => {
    const res = await fetch('/api/credits');
    const json = await res.json() as { success: boolean; data?: { balance: number; plan: string } };
    if (json.success && json.data) {
      const dailyLimit: Record<string, number | null> = { free: 5, maker: null, pro: null, enterprise: null };
      set({
        credits: {
          balance: json.data.balance,
          plan: json.data.plan as Credits['plan'],
          daily_limit: dailyLimit[json.data.plan] ?? null,
        },
      });
    }
  },

  fetchProjects: async () => {
    set({ projectsLoading: true });
    try {
      const res = await fetch('/api/projects');
      const json = await res.json() as { success: boolean; data?: Project[] };
      if (json.success && json.data) {
        set({ projects: json.data });
      }
    } finally {
      set({ projectsLoading: false });
    }
  },

  setSelectedProjectId: (id) => set({ selectedProjectId: id }),

  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),

  updateProjectStatus: (id, status) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.id === id ? { ...p, status, updated_at: new Date().toISOString() } : p
      ),
    })),

  addMessage: (projectId, message) =>
    set((state) => ({
      messagesByProject: {
        ...state.messagesByProject,
        [projectId]: [...(state.messagesByProject[projectId] ?? []), message],
      },
    })),

  setAgentRunning: (running, step = null) =>
    set({ isAgentRunning: running, agentStep: running ? step : null }),

  deductCredits: (amount) =>
    set((state) => ({
      credits: state.credits
        ? { ...state.credits, balance: Math.max(0, state.credits.balance - amount) }
        : null,
    })),
}));
