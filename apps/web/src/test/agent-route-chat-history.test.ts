import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * POST /api/agent consigne la conversation du projet.
 *
 * La demande de l'utilisateur est écrite quand le pipeline est ACCEPTÉ, la
 * réponse de l'agent à la fin du flux — par le serveur, pas par l'onglet.
 * Une panne de l'historique ne doit jamais faire échouer le pipeline.
 */

const inserts = vi.hoisted(() => [] as Array<{ table: string; row: Record<string, unknown> }>);
const adminInsertError = vi.hoisted(() => ({ value: null as { message: string } | null }));

const supabaseMock = vi.hoisted(() => ({
  createRouteHandlerClient: vi.fn(),
  createAdminClient: vi.fn(() => ({
    rpc: vi.fn(),
    from: (table: string) => ({
      insert: async (row: Record<string, unknown>) => {
        inserts.push({ table, row });
        return { error: adminInsertError.value };
      },
    }),
  })),
}));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

vi.mock('@/shared/lib/ratelimit', () => ({
  checkRateLimit: vi.fn().mockResolvedValue({ success: true, remaining: 2 }),
}));

vi.mock('@/app/api/agent/lib/credits', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/app/api/agent/lib/credits')>();
  return {
    ...actual,
    reservePipelineCredits: vi.fn(async () => null),
    releasePipelineReservation: vi.fn(async () => {}),
  };
});

const runSimulatorAgentMock = vi.hoisted(() => vi.fn());
vi.mock('@/app/api/agent/lib/simulator', () => ({ runSimulatorAgent: runSimulatorAgentMock }));
vi.mock('@/app/api/agent/lib/orchestrator-bridge', () => ({ runRealOrchestrator: vi.fn() }));
vi.mock('@/app/api/agent/lib/local-pipeline', () => ({ runLocalPipeline: vi.fn() }));
vi.mock('@/app/api/agent/lib/agent-mode', () => ({
  resolveAgentMode: () => 'simulator',
  isOrchestratorAvailable: () => false,
}));

import { POST } from '@/app/api/agent/route';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

function makeClient() {
  return {
    auth: { getUser: async () => ({ data: { user: { id: 'u1' } } }) },
    from: (table: string) => ({
      select: () => ({
        eq: () => ({
          single: async () => ({
            data:
              table === 'projects'
                ? { id: PROJECT_ID, status: 'INITIAL', iteration_count: 0, pcb_state: null }
                : { balance: 100, plan: 'pro' },
            error: null,
          }),
        }),
      }),
    }),
  };
}

function makeRequest(prompt = 'un régulateur 3V3') {
  return { json: async () => ({ projectId: PROJECT_ID, prompt }) } as never;
}

async function drain(res: Response): Promise<string> {
  const reader = res.body?.getReader();
  if (!reader) return '';
  const decoder = new TextDecoder();
  let out = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    out += decoder.decode(value, { stream: true });
  }
  return out;
}

beforeEach(() => {
  vi.clearAllMocks();
  inserts.length = 0;
  adminInsertError.value = null;
  supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient());
  runSimulatorAgentMock.mockImplementation(
    async ({ sink }: { sink: { emit: (ev: unknown) => Promise<void> } }) => {
      await sink.emit({ type: 'token', content: 'Schéma ' });
      await sink.emit({ type: 'step', step: 'SCHEMA' });
      await sink.emit({ type: 'token', content: 'prêt.' });
      await sink.emit({ type: 'done' });
    },
  );
});

describe('POST /api/agent — historique de discussion', () => {
  it('consigne la demande puis la réponse de l’agent, dans cet ordre', async () => {
    const res = await POST(makeRequest('un blinker NE555'));
    await drain(res);

    const messages = inserts.filter((i) => i.table === 'project_messages').map((i) => i.row);
    expect(messages).toEqual([
      { project_id: PROJECT_ID, user_id: 'u1', role: 'user', content: 'un blinker NE555' },
      { project_id: PROJECT_ID, user_id: 'u1', role: 'assistant', content: 'Schéma prêt.' },
    ]);
  });

  it('consigne aussi l’erreur qui a interrompu le pipeline, comme la bulle l’affichait', async () => {
    runSimulatorAgentMock.mockImplementation(
      async ({ sink }: { sink: { emit: (ev: unknown) => Promise<void> } }) => {
        await sink.emit({ type: 'token', content: 'Début' });
        throw new Error('service KiCad injoignable');
      },
    );
    const res = await POST(makeRequest());
    const body = await drain(res);

    expect(body).toContain('service KiCad injoignable');
    const assistant = inserts.find((i) => i.row['role'] === 'assistant');
    expect(assistant?.row['content']).toBe('Début\n\n_Error: service KiCad injoignable_');
  });

  it('ne fait pas échouer le pipeline quand l’historique est indisponible', async () => {
    adminInsertError.value = { message: 'relation "project_messages" does not exist' };
    const res = await POST(makeRequest());
    const body = await drain(res);

    expect(res.status).toBe(200);
    expect(runSimulatorAgentMock).toHaveBeenCalledTimes(1);
    expect(body).toContain('"type":"done"');
  });
});
