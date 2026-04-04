import { create } from 'zustand';
import type { Project, Message, Credits, PCBStatus, PCBState } from '@layrix/types';
import { createSupabaseBrowserClient } from '@/shared/lib/supabase-browser';

interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
}

interface AppState {
  // Auth
  user: AuthUser | null;

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

  // PCB state par projet (mis à jour par les events SSE de l'agent)
  pcbStateByProject: Record<string, PCBState>;

  // Actions
  fetchUser: () => Promise<void>;
  fetchProjects: () => Promise<void>;
  fetchCredits: () => Promise<void>;
  createProject: (name: string) => Promise<Project | null>;
  setSelectedProjectId: (id: string | null) => void;
  addProject: (project: Project) => void;
  updateProjectName: (id: string, name: string) => void;
  removeProject: (id: string) => void;
  updateProjectStatus: (id: string, status: PCBStatus) => void;
  addMessage: (projectId: string, message: Message) => void;
  setAgentRunning: (running: boolean, step?: AppState['agentStep']) => void;
  deductCredits: (amount: number) => void;
  setPcbState: (projectId: string, state: Partial<PCBState>) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  projects: [],
  projectsLoading: false,
  selectedProjectId: null,
  messagesByProject: {},
  credits: null,
  isAgentRunning: false,
  agentStep: null,
  pcbStateByProject: {},

  fetchUser: async () => {
    const supabase = createSupabaseBrowserClient();
    const { data: { user } } = await supabase.auth.getUser();
    if (user) {
      set({
        user: {
          id: user.id,
          email: user.email ?? '',
          full_name: (user.user_metadata['full_name'] as string | undefined) ?? null,
          avatar_url: (user.user_metadata['avatar_url'] as string | undefined) ?? null,
        },
      });
    }
  },

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

  createProject: async (name) => {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const json = await res.json() as { success: boolean; data?: Project };
    if (!json.success || !json.data) return null;
    set((state) => ({ projects: [json.data!, ...state.projects] }));
    return json.data;
  },

  setSelectedProjectId: (id) => set({ selectedProjectId: id }),

  addProject: (project) =>
    set((state) => ({ projects: [project, ...state.projects] })),

  updateProjectName: (id, name) =>
    set((state) => ({
      projects: state.projects.map((p) =>
        p.id === id ? { ...p, name, updated_at: new Date().toISOString() } : p
      ),
    })),

  removeProject: (id) =>
    set((state) => ({
      projects: state.projects.filter((p) => p.id !== id),
    })),

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

  deductCredits: (amount) => {
    // Optimistic local update for immediate UI feedback
    set((state) => ({
      credits: state.credits
        ? { ...state.credits, balance: Math.max(0, state.credits.balance - amount) }
        : null,
    }));
    // Re-fetch from DB to stay in sync (fire-and-forget)
    void fetch('/api/credits')
      .then((r) => r.json() as Promise<{ success: boolean; data?: { balance: number; plan: string } }>)
      .then((json) => {
        if (json.success && json.data) {
          set((state) => ({
            credits: state.credits
              ? { ...state.credits, balance: json.data!.balance }
              : null,
          }));
        }
      })
      .catch(() => { /* keep optimistic value on network error */ });
  },

  setPcbState: (projectId, partial) =>
    set((state) => {
      const existing = state.pcbStateByProject[projectId] ?? { projectId, status: 'INITIAL' as PCBStatus, iteration: 0 };
      // `pcb_status` is a signal field emitted by tool stubs to carry the PCBStatus value
      // without colliding with the tool result's own `status: 'success'` field.
      const { pcb_status, ...rest } = partial as typeof partial & { pcb_status?: PCBStatus };
      return {
        pcbStateByProject: {
          ...state.pcbStateByProject,
          [projectId]: {
            ...existing,
            ...rest,
            ...(pcb_status ? { status: pcb_status } : {}),
          },
        },
      };
    }),
}));
