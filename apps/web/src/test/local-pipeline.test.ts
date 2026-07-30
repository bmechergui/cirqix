import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * runLocalPipeline — chemin de repli emprunté quand l'orchestrateur échoue sur
 * une erreur de crédit/402. Il enchaîne les mêmes handlers que l'orchestrateur,
 * mais persiste lui-même projects.status.
 *
 * Enjeu : POST /api/jlcpcb/order autorise une commande dès que projects.status
 * vaut DRC_CLEAN. Ce pipeline passait un statut CODÉ EN DUR par étape, sans
 * regarder ce que le handler avait réellement renvoyé — donc un DRC en erreur,
 * ou un DRC ayant trouvé des violations, était tout de même persisté DRC_CLEAN
 * et débloquait la commande.
 *
 * Invariant : le handler fait foi. Le pipeline ne promeut jamais un statut que
 * le handler n'a pas accordé.
 */

const agentsMock = vi.hoisted(() => ({ executeToolStub: vi.fn() }));
vi.mock('@cirqix/agents', () => agentsMock);

vi.mock('../app/api/agent/lib/kicad-storage', () => ({
  uploadKicadArtifact: vi.fn().mockResolvedValue({ signedUrl: undefined }),
}));

vi.mock('@cirqix/logger', () => ({
  logger: { child: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
}));

import { runLocalPipeline } from '../app/api/agent/lib/local-pipeline';

function makeSupabase(rpcError: { message: string } | null = null) {
  const updates: Array<Record<string, unknown>> = [];
  const rpc = vi.fn().mockResolvedValue({ error: rpcError });
  const client = {
    rpc,
    from: () => ({
      update: (payload: Record<string, unknown>) => {
        updates.push(payload);
        return { eq: () => Promise.resolve({ data: null, error: null }) };
      },
    }),
  };
  return { client, updates, rpc };
}

function makeController() {
  const chunks: string[] = [];
  const decoder = new TextDecoder();
  const controller = {
    enqueue: (bytes: Uint8Array) => {
      chunks.push(decoder.decode(bytes));
    },
  };
  return { controller, chunks };
}

/** Statuts successivement persistés en base, dans l'ordre. */
async function runAndCollect(rpcError: { message: string } | null = null) {
  const { client, updates, rpc } = makeSupabase(rpcError);
  const { controller, chunks } = makeController();

  await runLocalPipeline({
    controller: controller as never,
    encoder: new TextEncoder(),
    supabase: client as never,
    userId: 'u1',
    projectId: 'p1',
    prompt: 'LED blinker',
    iterationStart: 0,
    balanceStart: 10,
  });

  return {
    statuses: updates.map((u) => u['status']),
    lastStatus: updates[updates.length - 1]?.['status'],
    sse: chunks.join(''),
    rpc,
  };
}

const OK = {
  call_agent_schema: { status: 'success', pcb_status: 'SCHEMA_DONE' },
  call_agent_erc: { status: 'success', pcb_status: 'ERC_CLEAN' },
  call_agent_placement: { status: 'success', pcb_status: 'PLACEMENT_DONE' },
  call_agent_routing: { status: 'success', pcb_status: 'ROUTING_DONE', routed_percent: 100 },
  call_agent_drc: { status: 'success', pcb_status: 'DRC_CLEAN', drc_clean: true },
} as Record<string, Record<string, unknown>>;

/** Rejoue le pipeline nominal, en remplaçant le résultat d'un seul outil. */
function mockPipeline(overrides: Record<string, Record<string, unknown>> = {}) {
  agentsMock.executeToolStub.mockImplementation(async (name: string) => ({
    ...(OK[name] ?? { status: 'success' }),
    ...(overrides[name] ?? {}),
  }));
}

beforeEach(() => {
  agentsMock.executeToolStub.mockReset();
  mockPipeline();
});

describe('pipeline nominal', () => {
  it('fait progresser le statut jusqu’à DRC_CLEAN', async () => {
    const { statuses, lastStatus } = await runAndCollect();

    expect(statuses).toEqual([
      'SCHEMA_DONE',
      'ERC_CLEAN',
      'PLACEMENT_DONE',
      'ROUTING_DONE',
      'DRC_CLEAN',
    ]);
    expect(lastStatus).toBe('DRC_CLEAN');
  });

  it('débite le coût complet via la RPC atomique avant done', async () => {
    const { rpc, sse } = await runAndCollect();

    expect(rpc).toHaveBeenCalledWith('deduct_credits', {
      p_user_id: 'u1',
      p_amount: 8.5,
      p_action: 'full_pcb_pipeline',
      p_project_id: 'p1',
    });
    expect(sse).toContain('"type":"done"');
  });

  it('n’émet pas done quand le débit atomique échoue', async () => {
    const { lastStatus, sse } = await runAndCollect({ message: 'insufficient_credits' });

    expect(sse).toContain('"type":"error"');
    expect(sse).not.toContain('"type":"done"');
    expect(lastStatus).toBe('ROUTING_DONE');
  });
});

describe('le handler fait foi — jamais de promotion non accordée', () => {
  it('DRC trouvant des violations → reste ROUTING_DONE, la commande reste bloquée', async () => {
    mockPipeline({
      call_agent_drc: {
        status: 'success',
        pcb_status: 'ROUTING_DONE',
        drc_clean: false,
        drcViolations: [{ type: 'clearance' }],
      },
    });

    const { lastStatus } = await runAndCollect();

    expect(lastStatus).not.toBe('DRC_CLEAN');
    expect(lastStatus).toBe('ROUTING_DONE');
  });

  it('DRC en erreur → jamais DRC_CLEAN persisté', async () => {
    mockPipeline({
      call_agent_drc: { status: 'error', error: 'kicad-cli indisponible' },
    });

    const { statuses, sse } = await runAndCollect();

    expect(statuses).not.toContain('DRC_CLEAN');
    expect(sse).toContain('kicad-cli indisponible');
  });

  it('routage en erreur → arrête le pipeline, le DRC n’est jamais lancé', async () => {
    mockPipeline({
      call_agent_routing: { status: 'error', error: 'service de routage injoignable' },
    });

    const { statuses } = await runAndCollect();
    const called = agentsMock.executeToolStub.mock.calls.map((c) => c[0]);

    expect(called).not.toContain('call_agent_drc');
    expect(statuses).not.toContain('ROUTING_DONE');
    expect(statuses).not.toContain('DRC_CLEAN');
  });

  it('placement en erreur → arrête le pipeline immédiatement', async () => {
    mockPipeline({
      call_agent_placement: { status: 'error', error: 'conteneur pcbnew arrêté' },
    });

    const { statuses } = await runAndCollect();
    const called = agentsMock.executeToolStub.mock.calls.map((c) => c[0]);

    expect(called).not.toContain('call_agent_routing');
    expect(statuses).toEqual(['SCHEMA_DONE', 'ERC_CLEAN']);
  });

  it('signale l’échec au client via un event SSE error', async () => {
    mockPipeline({
      call_agent_drc: { status: 'error', error: 'boom' },
    });

    const { sse } = await runAndCollect();

    expect(sse).toContain('"type":"error"');
  });
});
