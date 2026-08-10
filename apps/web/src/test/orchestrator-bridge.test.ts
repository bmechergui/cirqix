import { beforeEach, describe, expect, it, vi } from 'vitest';

const agentsMock = vi.hoisted(() => ({ runOrchestrator: vi.fn() }));
vi.mock('@cirqix/agents', () => agentsMock);
vi.mock('../app/api/agent/lib/kicad-storage', () => ({
  uploadKicadArtifact: vi.fn().mockResolvedValue({ signedUrl: undefined }),
}));
vi.mock('@cirqix/logger', () => ({
  logger: { child: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
}));

import { CreditDeductionError } from '../app/api/agent/lib/credits';
import { runRealOrchestrator } from '../app/api/agent/lib/orchestrator-bridge';

function makeController() {
  const chunks: string[] = [];
  const decoder = new TextDecoder();
  return {
    chunks,
    controller: { enqueue: (bytes: Uint8Array) => chunks.push(decoder.decode(bytes)) },
  };
}

function makeClient(rpcError: { message: string } | null = null) {
  const updates: Array<Record<string, unknown>> = [];
  const rpc = vi.fn().mockResolvedValue({ data: true, error: rpcError });
  return {
    rpc,
    updates,
    client: {
      rpc,
      from: () => ({
        update: (payload: Record<string, unknown>) => {
          updates.push(payload);
          return { eq: async () => ({ error: null }) };
        },
      }),
    },
  };
}

function finalEvents() {
  return (async function* () {
    yield { type: 'pcb_state', state: { pcb_status: 'DRC_CLEAN', iteration: 1 } };
    yield { type: 'done' };
  })();
}

beforeEach(() => {
  vi.clearAllMocks();
  agentsMock.runOrchestrator.mockImplementation(finalEvents);
});

describe('orchestrator finalization', () => {
  it('ne publie ni ne persiste DRC_CLEAN si la transaction finale échoue', async () => {
    const { client, updates } = makeClient({ message: 'insufficient_credits' });
    const { controller, chunks } = makeController();

    await expect(runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    })).rejects.toBeInstanceOf(CreditDeductionError);

    expect(updates).toHaveLength(0);
    expect(chunks.join('')).not.toContain('DRC_CLEAN');
    expect(chunks.join('')).not.toContain('"type":"done"');
  });

  it('ne persiste pas iteration_count sur les étapes intermédiaires', async () => {
    // `iteration` est figé à iterationStart + 1 pour tout le run
    // (orchestrator-bridge.ts, `mergedState.iteration ?? iterationStart + 1`).
    // Si une étape intermédiaire écrivait déjà cette valeur dans
    // projects.iteration_count, la garde `stale_iteration` de
    // finalize_pipeline_success — qui exige p_iteration_count = iteration_count
    // + 1 — refuserait la finalisation, et le pipeline échouerait à sa toute
    // dernière étape sans facturer ni promouvoir. Le compteur n'appartient
    // qu'à la RPC.
    const { client, updates } = makeClient();
    const { controller } = makeController();
    agentsMock.runOrchestrator.mockImplementation(() => (async function* () {
      yield { type: 'pcb_state', state: { pcb_status: 'ROUTING_DONE', iteration: 1 } };
      yield { type: 'pcb_state', state: { pcb_status: 'DRC_CLEAN', iteration: 1 } };
      yield { type: 'done' };
    })());

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(updates).toHaveLength(1);
    expect(updates[0]).not.toHaveProperty('iteration_count');
  });

  it('publie DRC_CLEAN et done après la transaction finale réussie', async () => {
    const { client, rpc } = makeClient();
    const { controller, chunks } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(rpc).toHaveBeenCalledWith(
      'finalize_pipeline_success',
      expect.objectContaining({ p_project_id: 'p1', p_iteration_count: 1 }),
    );
    expect(chunks.join('')).toContain('DRC_CLEAN');
    expect(chunks.join('')).toContain('"type":"done"');
  });
});
