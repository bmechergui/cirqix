import { create } from 'zustand';
import type { Credits } from '@layrix/types';
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

  // Credits
  credits: Credits | null;

  // Actions
  fetchUser: () => Promise<void>;
  fetchCredits: () => Promise<void>;
  deductCredits: (amount: number) => void;
}

export const useAppStore = create<AppState>((set) => ({
  user: null,
  credits: null,

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
      const dailyLimit: Record<string, number | null> = { free: 5, pro: null, pro_max: null, enterprise: null };
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
      .catch(() => { /* keep optimistic value */ });
  },
}));
