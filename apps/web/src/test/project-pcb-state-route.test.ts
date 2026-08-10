import { beforeEach, describe, expect, it, vi } from 'vitest';

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { GET, PATCH } from '@/app/api/projects/[id]/pcb-state/route';

/**
 * Enregistre les colonnes passées à `.eq()` pour vérifier que la requête filtre
 * bien sur le propriétaire, et pas seulement sur l'id du projet.
 */
function makeClient() {
  const filters: Array<[string, unknown]> = [];
  const chain: Record<string, unknown> = {};
  chain['eq'] = (col: string, val: unknown) => {
    filters.push([col, val]);
    return chain;
  };
  chain['single'] = async () => ({ data: { pcb_state: null }, error: null });

  const client = {
    auth: { getUser: async () => ({ data: { user: { id: 'u1' } } }) },
    from: () => ({ select: () => chain }),
  };
  return { client, filters };
}

beforeEach(() => vi.clearAllMocks());

describe('GET /api/projects/:id/pcb-state', () => {
  // La route construit ensuite des URLs signées sous `${user.id}/${projectId}/`.
  // Sans ce filtre, la seule barrière entre deux comptes serait la policy RLS —
  // une défense unique, que rien ne vérifie au runtime.
  it('filtre sur le propriétaire, pas seulement sur l’id du projet', async () => {
    const { client, filters } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    const response = await GET({} as never, { params: Promise.resolve({ id: 'p1' }) });

    expect(response.status).toBe(200);
    expect(filters).toContainEqual(['user_id', 'u1']);
    expect(filters).toContainEqual(['id', 'p1']);
  });

  it('refuse un appel non authentifié', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue({
      auth: { getUser: async () => ({ data: { user: null } }) },
    });

    const response = await GET({} as never, { params: Promise.resolve({ id: 'p1' }) });

    expect(response.status).toBe(401);
  });
});

describe('PATCH /api/projects/:id/pcb-state', () => {
  it('refuse toute écriture client sur l’état géré par le pipeline', async () => {
    const response = await PATCH(
      { json: async () => ({ status: 'DRC_CLEAN' }) } as never,
      { params: Promise.resolve({ id: 'p1' }) },
    );

    expect(response.status).toBe(405);
    expect(response.headers.get('allow')).toBe('GET');
    expect(await response.json()).toMatchObject({
      success: false,
      error: 'PCB state is pipeline-managed',
    });
  });
});
