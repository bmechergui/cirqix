import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Câblage de la réservation de crédits dans POST /api/agent (issue #117).
 *
 * La retenue doit être posée AVANT que le pipeline ne démarre — poser après
 * reviendrait à ne rien garantir — et levée quoi qu'il arrive ensuite.
 */

const supabaseMock = vi.hoisted(() => ({
  createRouteHandlerClient: vi.fn(),
  createAdminClient: vi.fn(() => ({ rpc: vi.fn() })),
}));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

vi.mock('@/shared/lib/ratelimit', () => ({
  checkRateLimit: vi.fn().mockResolvedValue({ success: true, remaining: 2 }),
}));

const reserveMock = vi.hoisted(() => vi.fn());
const releaseMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('@/app/api/agent/lib/credits', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/app/api/agent/lib/credits')>();
  return {
    ...actual,
    reservePipelineCredits: reserveMock,
    releasePipelineReservation: releaseMock,
  };
});

const order: string[] = [];
const runSimulatorAgentMock = vi.hoisted(() => vi.fn(async () => {}));
const runRealOrchestratorMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('@/app/api/agent/lib/simulator', () => ({ runSimulatorAgent: runSimulatorAgentMock }));
vi.mock('@/app/api/agent/lib/orchestrator-bridge', () => ({
  runRealOrchestrator: runRealOrchestratorMock,
}));
vi.mock('@/app/api/agent/lib/local-pipeline', () => ({ runLocalPipeline: vi.fn() }));

const agentModeMock = vi.hoisted(() => ({ mode: 'orchestrator', available: true }));
vi.mock('@/app/api/agent/lib/agent-mode', () => ({
  resolveAgentMode: () => agentModeMock.mode,
  isOrchestratorAvailable: () => agentModeMock.available,
}));

import { POST } from '@/app/api/agent/route';
import { getProjectPlan } from '@cirqix/agents';
import {
  InsufficientCreditsError,
  CreditReservationError,
  PipelineAlreadyRunningError,
} from '@/app/api/agent/lib/credits';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const RESERVATION_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

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

function makeRequest() {
  return { json: async () => ({ projectId: PROJECT_ID, prompt: 'un régulateur 3V3' }) } as never;
}

/** Draine le flux SSE : le `finally` de la route ne s'exécute qu'après. */
async function drain(res: Response): Promise<void> {
  const reader = res.body?.getReader();
  if (!reader) return;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done } = await reader.read();
    if (done) break;
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  order.length = 0;
  agentModeMock.mode = 'orchestrator';
  agentModeMock.available = true;
  reserveMock.mockImplementation(async () => {
    order.push('reserve');
    return RESERVATION_ID;
  });
  releaseMock.mockImplementation(async () => {
    order.push('release');
  });
  runRealOrchestratorMock.mockImplementation(async () => {
    order.push('pipeline');
  });
  supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient());
});

describe('POST /api/agent — réservation de crédits', () => {
  it('réserve avant le pipeline et libère après', async () => {
    const res = await POST(makeRequest());
    await drain(res);

    expect(order).toEqual(['reserve', 'pipeline', 'release']);
    expect(releaseMock).toHaveBeenCalledWith(expect.anything(), RESERVATION_ID);
  });

  it('libère la retenue même quand le pipeline échoue', async () => {
    // Sans cela, un pipeline en erreur gèlerait le crédit jusqu'au TTL et
    // l'utilisateur ne pourrait pas relancer immédiatement.
    runRealOrchestratorMock.mockImplementation(async () => {
      order.push('pipeline');
      throw new Error('orchestrateur injoignable');
    });

    const res = await POST(makeRequest());
    await drain(res);

    expect(order).toEqual(['reserve', 'pipeline', 'release']);
  });

  it('répond 402 sans lancer le pipeline quand le solde ne suffit plus', async () => {
    reserveMock.mockRejectedValue(new InsufficientCreditsError());

    const res = await POST(makeRequest());

    expect(res.status).toBe(402);
    expect(runRealOrchestratorMock).not.toHaveBeenCalled();
    expect(releaseMock).not.toHaveBeenCalled();
  });

  it('répond 500, et non 402, quand la réservation tombe en panne', async () => {
    // Annoncer « crédits insuffisants » sur une panne de base enverrait
    // l'utilisateur acheter des crédits qu'il possède déjà.
    reserveMock.mockRejectedValue(new CreditReservationError('boom'));

    const res = await POST(makeRequest());

    expect(res.status).toBe(500);
    expect(runRealOrchestratorMock).not.toHaveBeenCalled();
  });

  it('répond 409 quand un pipeline tourne déjà sur ce projet', async () => {
    // Un double-clic ne doit ni facturer, ni démarrer un second run, ni être
    // présenté comme un problème de solde.
    reserveMock.mockRejectedValue(new PipelineAlreadyRunningError());

    const res = await POST(makeRequest());

    expect(res.status).toBe(409);
    expect(runRealOrchestratorMock).not.toHaveBeenCalled();
    expect(releaseMock).not.toHaveBeenCalled();
  });

  it.each([
    ['solde insuffisant (402)', () => reserveMock.mockRejectedValue(new InsufficientCreditsError())],
    ['run déjà en cours (409)', () => reserveMock.mockRejectedValue(new PipelineAlreadyRunningError())],
    ['réservation en panne (500)', () => reserveMock.mockRejectedValue(new CreditReservationError('x'))],
  ])('ne laisse aucun plan orphelin — %s', async (_label, arrange) => {
    // Le plan est rangé dans une map module-singleton, libérée par le `finally`
    // du flux SSE. Le semer AVANT les retours anticipés laissait une entrée
    // orpheline à chaque échec : un compte gratuit sans crédit qui réessaie
    // faisait grossir la map indéfiniment. Fuite non bornée, sur le chemin
    // d'échec le plus courant.
    arrange();

    await POST(makeRequest());

    expect(getProjectPlan(PROJECT_ID)).toBeUndefined();
  });

  it('libère le plan à la fin d\'un run nominal', async () => {
    const res = await POST(makeRequest());
    await drain(res);

    expect(getProjectPlan(PROJECT_ID)).toBeUndefined();
  });

  it('ne réserve rien en mode simulateur', async () => {
    // Le simulateur ne facture pas (migration 012) : retenir des crédits pour
    // une démonstration bloquerait un solde que personne ne débitera.
    agentModeMock.mode = 'simulator';

    const res = await POST(makeRequest());
    await drain(res);

    expect(reserveMock).not.toHaveBeenCalled();
    expect(releaseMock).not.toHaveBeenCalled();
    expect(runSimulatorAgentMock).toHaveBeenCalled();
  });

  it("ne réserve rien quand l'orchestrateur est demandé mais indisponible", async () => {
    // La route bascule alors sur le simulateur, qui ne facture pas.
    agentModeMock.available = false;

    const res = await POST(makeRequest());
    await drain(res);

    expect(reserveMock).not.toHaveBeenCalled();
    expect(runSimulatorAgentMock).toHaveBeenCalled();
  });
});
