import { create } from 'zustand';
import type { Credits, Project, Message, PCBState, AgentStep } from '@cirqix/types';
import { createSupabaseBrowserClient } from '@/shared/lib/supabase-browser';
import type { PcbStage } from '@/entities/project';

interface AuthUser {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
}

interface ProjectsApiResponse {
  success: boolean;
  data?: Project[];
  error?: string;
}

interface ProjectApiResponse {
  success: boolean;
  data?: Project;
  error?: string;
}

interface PcbStateApiResponse {
  success: boolean;
  data?: { pcb_state: PCBState | null };
  error?: string;
}

interface AppState {
  user: AuthUser | null;
  credits: Credits | null;

  projects: Project[];
  projectsLoading: boolean;
  projectsError: string | null;

  messagesByProject: Record<string, Message[]>;
  pcbStateByProject: Record<string, PCBState | null>;

  agentStep: AgentStep;
  agentBusy: boolean;
  selectedStage: Record<string, PcbStage>;

  fetchUser: () => Promise<void>;
  fetchCredits: () => Promise<void>;
  deductCredits: (amount: number) => void;

  fetchProjects: () => Promise<void>;
  createProject: (input: { name: string; description: string }) => Promise<Project | null>;
  deleteProject: (id: string) => Promise<boolean>;

  fetchPcbState: (projectId: string) => Promise<void>;
  setPcbState: (projectId: string, state: PCBState | null) => void;

  appendMessage: (projectId: string, msg: Message) => void;
  patchLastAssistantMessage: (projectId: string, chunk: string) => void;
  setMessages: (projectId: string, msgs: Message[]) => void;

  setAgentStep: (step: AgentStep) => void;
  setAgentBusy: (busy: boolean) => void;
  setSelectedStage: (projectId: string, stage: PcbStage) => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  user: null,
  credits: null,

  projects: [],
  projectsLoading: false,
  projectsError: null,

  messagesByProject: {},
  pcbStateByProject: {},

  agentStep: null,
  agentBusy: false,
  selectedStage: {},

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
    const json = (await res.json()) as {
      success: boolean;
      data?: { balance: number; plan: string };
    };
    if (json.success && json.data) {
      const dailyLimit: Record<string, number | null> = {
        free: 5,
        pro: null,
        pro_max: null,
        enterprise: null,
      };
      set({
        credits: {
          balance: json.data.balance,
          plan: json.data.plan as Credits['plan'],
          daily_limit: dailyLimit[json.data.plan] ?? null,
        },
      });
    }
  },

  deductCredits: (amount) => {
    set((state) => ({
      credits: state.credits
        ? { ...state.credits, balance: Math.max(0, state.credits.balance - amount) }
        : null,
    }));
  },

  fetchProjects: async () => {
    set({ projectsLoading: true, projectsError: null });
    try {
      const res = await fetch('/api/projects', { cache: 'no-store' });
      const json = (await res.json()) as ProjectsApiResponse;
      if (!res.ok || !json.success || !json.data) {
        throw new Error(json.error ?? 'Failed to load projects');
      }
      set({ projects: json.data, projectsLoading: false });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error';
      set({ projectsError: message, projectsLoading: false });
    }
  },

  createProject: async ({ name, description }) => {
    const res = await fetch('/api/projects', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, description }),
    });
    const json = (await res.json()) as ProjectApiResponse;
    if (!res.ok || !json.success || !json.data) return null;
    set((s) => ({ projects: [json.data!, ...s.projects] }));
    return json.data;
  },

  deleteProject: async (id) => {
    const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' });
    if (!res.ok) return false;
    set((s) => ({ projects: s.projects.filter((p) => p.id !== id) }));
    return true;
  },

  fetchPcbState: async (projectId) => {
    const res = await fetch(`/api/projects/${projectId}/pcb-state`, { cache: 'no-store' });
    if (!res.ok) return;
    const json = (await res.json()) as PcbStateApiResponse;
    if (json.success && json.data) {
      set((s) => ({
        pcbStateByProject: {
          ...s.pcbStateByProject,
          [projectId]: json.data!.pcb_state ?? null,
        },
      }));
    }
  },

  setPcbState: (projectId, state) =>
    set((s) => ({
      pcbStateByProject: { ...s.pcbStateByProject, [projectId]: state },
    })),

  appendMessage: (projectId, msg) =>
    set((s) => ({
      messagesByProject: {
        ...s.messagesByProject,
        [projectId]: [...(s.messagesByProject[projectId] ?? []), msg],
      },
    })),

  patchLastAssistantMessage: (projectId, chunk) => {
    const list = get().messagesByProject[projectId] ?? [];
    if (list.length === 0) return;
    const last = list[list.length - 1]!;
    if (last.role !== 'assistant') return;
    const updated: Message = { ...last, content: last.content + chunk };
    set((s) => ({
      messagesByProject: {
        ...s.messagesByProject,
        [projectId]: [...list.slice(0, -1), updated],
      },
    }));
  },

  setMessages: (projectId, msgs) =>
    set((s) => ({
      messagesByProject: { ...s.messagesByProject, [projectId]: msgs },
    })),

  setAgentStep: (step) => set({ agentStep: step }),
  setAgentBusy: (busy) => set({ agentBusy: busy }),
  setSelectedStage: (projectId, stage) =>
    set((s) => ({
      selectedStage: { ...s.selectedStage, [projectId]: stage },
    })),
}));
