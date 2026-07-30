import { describe, expect, it } from 'vitest';
import { PATCH } from '@/app/api/projects/[id]/pcb-state/route';

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
