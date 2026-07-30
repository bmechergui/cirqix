import { beforeEach, describe, expect, it, vi } from 'vitest';

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { PATCH } from '@/app/api/projects/[id]/route';

function makeClient() {
  const updates: Array<Record<string, unknown>> = [];
  const client = {
    auth: { getUser: async () => ({ data: { user: { id: 'u1' } } }) },
    from: () => ({
      update: (payload: Record<string, unknown>) => {
        updates.push(payload);
        return {
          eq: () => ({
            select: () => ({
              single: async () => ({
                data: { id: 'p1', ...payload, status: 'INITIAL' },
                error: null,
              }),
            }),
          }),
        };
      },
    }),
  };
  return { client, updates };
}

beforeEach(() => vi.clearAllMocks());

describe('PATCH /api/projects/:id', () => {
  it('rejette toute tentative de transition de statut par le client', async () => {
    const { client, updates } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    const response = await PATCH(
      { json: async () => ({ status: 'DRC_CLEAN' }) } as never,
      { params: Promise.resolve({ id: 'p1' }) },
    );

    expect(response.status).toBe(400);
    expect(updates).toHaveLength(0);
  });

  it('autorise encore la modification du nom et de la description uniquement', async () => {
    const { client, updates } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    const response = await PATCH(
      { json: async () => ({ name: 'Board', description: 'Power stage' }) } as never,
      { params: Promise.resolve({ id: 'p1' }) },
    );

    expect(response.status).toBe(200);
    expect(updates).toEqual([{ name: 'Board', description: 'Power stage' }]);
  });
});
