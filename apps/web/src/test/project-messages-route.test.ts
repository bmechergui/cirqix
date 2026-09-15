import { beforeEach, describe, expect, it, vi } from 'vitest';

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { GET } from '@/app/api/projects/[id]/messages/route';

const PROJECT_ID = '22222222-2222-4222-8222-222222222222';

interface Row {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  created_at: string;
}

/** Faux client : enregistre les filtres et l'ordre demandés. */
function makeClient(rows: Row[], error: { message: string } | null = null) {
  const filters: Array<[string, unknown]> = [];
  const calls: { table?: string; order?: [string, unknown]; limit?: number } = {};
  const chain: Record<string, unknown> = {};
  chain['eq'] = (col: string, val: unknown) => {
    filters.push([col, val]);
    return chain;
  };
  chain['order'] = (col: string, opts: unknown) => {
    calls.order = [col, opts];
    return chain;
  };
  chain['limit'] = async (n: number) => {
    calls.limit = n;
    return { data: error ? null : rows, error };
  };
  const client = {
    auth: { getUser: async () => ({ data: { user: { id: 'u1' } } }) },
    from: (table: string) => {
      calls.table = table;
      return { select: () => chain };
    },
  };
  return { client, filters, calls };
}

beforeEach(() => vi.clearAllMocks());

describe('GET /api/projects/:id/messages', () => {
  it('refuse un appel non authentifié', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue({
      auth: { getUser: async () => ({ data: { user: null } }) },
    });
    const res = await GET({} as never, { params: Promise.resolve({ id: PROJECT_ID }) });
    expect(res.status).toBe(401);
  });

  it('refuse un identifiant de projet invalide', async () => {
    const { client } = makeClient([]);
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const res = await GET({} as never, { params: Promise.resolve({ id: 'pas-un-uuid' }) });
    expect(res.status).toBe(400);
  });

  it('filtre sur le propriétaire ET le projet — deux barrières, pas la seule RLS', async () => {
    const { client, filters, calls } = makeClient([]);
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const res = await GET({} as never, { params: Promise.resolve({ id: PROJECT_ID }) });
    expect(res.status).toBe(200);
    expect(calls.table).toBe('project_messages');
    expect(filters).toContainEqual(['project_id', PROJECT_ID]);
    expect(filters).toContainEqual(['user_id', 'u1']);
  });

  it('rend les messages dans l’ordre chronologique, les plus récents conservés', async () => {
    // La base rend du plus récent au plus ancien (pour borner aux N derniers) :
    // la route doit remettre la conversation dans l'ordre de lecture.
    const rows: Row[] = [
      { id: 'm2', role: 'assistant', content: 'Schéma prêt', created_at: '2026-09-15T10:00:05Z' },
      { id: 'm1', role: 'user', content: 'un blinker', created_at: '2026-09-15T10:00:00Z' },
    ];
    const { client, calls } = makeClient(rows);
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const res = await GET({} as never, { params: Promise.resolve({ id: PROJECT_ID }) });
    const json = (await res.json()) as { success: boolean; data: { messages: Row[] } };
    expect(calls.order).toEqual(['created_at', { ascending: false }]);
    expect(calls.limit).toBeGreaterThan(0);
    expect(json.success).toBe(true);
    expect(json.data.messages.map((m) => m.id)).toEqual(['m1', 'm2']);
  });

  it('rend 500 quand la lecture échoue — une erreur n’est pas un historique vide', async () => {
    const { client } = makeClient([], { message: 'relation does not exist' });
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const res = await GET({} as never, { params: Promise.resolve({ id: PROJECT_ID }) });
    expect(res.status).toBe(500);
  });
});
