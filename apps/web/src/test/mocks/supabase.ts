import { vi } from 'vitest';

// Supabase mock factory — retourne un client configurable par test
export function createSupabaseMock(overrides?: {
  user?: { id: string; email: string; user_metadata?: Record<string, unknown> } | null;
  creditsData?: { balance: number; plan: string } | null;
  creditsError?: { message: string } | null;
  projectsData?: unknown[] | null;
  projectsError?: { message: string } | null;
  insertData?: unknown | null;
  insertError?: { code?: string; message: string } | null;
  rpcError?: { message: string } | null;
  updateUserData?: { user: { id: string; email: string; user_metadata: Record<string, unknown> } } | null;
  updateUserError?: { message: string } | null;
  listData?: unknown[] | null;
  listError?: { message: string } | null;
}) {
  // undefined → use default; null → unauthenticated
  const user = overrides !== undefined && 'user' in overrides
    ? overrides.user
    : { id: 'user-123', email: 'test@example.com', user_metadata: { full_name: 'Test User', avatar_url: null } };

  const mockSingle = vi.fn().mockResolvedValue({
    data: overrides?.creditsData ?? { balance: 10, plan: 'free' },
    error: overrides?.creditsError ?? null,
  });

  const listResult = {
    data: overrides?.listData ?? overrides?.projectsData ?? [],
    error: overrides?.listError ?? overrides?.projectsError ?? null,
  };

  const mockSelect = vi.fn().mockReturnValue({
    eq: vi.fn().mockReturnValue({
      single: mockSingle,
      order: vi.fn().mockReturnValue({
        data: listResult.data,
        error: listResult.error,
        limit: vi.fn().mockResolvedValue(listResult),
      }),
    }),
    order: vi.fn().mockResolvedValue(listResult),
  });

  const mockInsert = vi.fn().mockReturnValue({
    select: vi.fn().mockReturnValue({
      single: vi.fn().mockResolvedValue({
        data: overrides?.insertData ?? null,
        error: overrides?.insertError ?? null,
      }),
    }),
  });

  const mockRpc = vi.fn().mockResolvedValue({
    error: overrides?.rpcError ?? null,
  });

  const updatedUser = overrides?.updateUserData?.user ?? {
    id: 'user-123',
    email: 'test@example.com',
    user_metadata: { full_name: 'Updated Name', avatar_url: null },
  };

  return {
    auth: {
      getUser: vi.fn().mockResolvedValue({ data: { user }, error: null }),
      signInWithPassword: vi.fn(),
      signUp: vi.fn(),
      signOut: vi.fn(),
      updateUser: vi.fn().mockResolvedValue({
        data: { user: updatedUser },
        error: overrides?.updateUserError ?? null,
      }),
    },
    from: vi.fn().mockReturnValue({
      select: mockSelect,
      insert: mockInsert,
    }),
    rpc: mockRpc,
  };
}
