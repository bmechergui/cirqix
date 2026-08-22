import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * `runJob` — le contrat de fin d'un run dans le worker.
 *
 * Deux invariants, chacun avec une conséquence concrète si on les rate.
 *
 * 1. LE RUN EST TOUJOURS CLOS. Un run laissé `running` bloque indéfiniment son
 *    projet : l'index unique de la migration 019 refuse un second run vivant, et
 *    la réservation de crédits reste posée. L'utilisateur ne pourrait plus rien
 *    lancer sur ce projet, sans comprendre pourquoi.
 *
 * 2. LE BATTEMENT EST TOUJOURS ARRÊTÉ. Un `setInterval` orphelin continuerait à
 *    rafraîchir le heartbeat d'un run mort — donc à le faire passer pour vivant
 *    auprès de la réconciliation, qui ne le récupérerait jamais.
 *
 * L'annulation est traitée à part : le pipeline ne LÈVE pas quand un run est
 * annulé, il cesse simplement de relancer du travail lourd. C'est donc ici que
 * se distingue un run mené à son terme d'un run interrompu.
 */

const agentsMock = vi.hoisted(() => ({
  runOrchestratorPipeline: vi.fn(),
  PgSink: class {
    constructor(
      public runId: string,
      public writer: { insert: (rows: unknown[]) => Promise<void> },
    ) {}
    emitted: unknown[] = [];
    async emit(ev: unknown): Promise<void> {
      this.emitted.push(ev);
    }
    async close(): Promise<void> {}
  },
}));
vi.mock('@cirqix/agents', () => agentsMock);
vi.mock('@cirqix/logger', () => ({
  logger: {
    child: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }),
  },
}));

import { runJob } from '../run-job.js';

const payload = {
  runId: '11111111-1111-4111-8111-111111111111',
  projectId: '22222222-2222-4222-8222-222222222222',
  userId: '33333333-3333-4333-8333-333333333333',
  prompt: 'un blinker NE555',
  iterationStart: 0,
};

function makeCtx(overrides: Record<string, unknown> = {}) {
  const finish = vi.fn().mockResolvedValue(undefined);
  const ctx = {
    supabase: {} as never,
    createStore: vi.fn(() => ({}) as never),
    createEventWriter: vi.fn(() => ({ insert: vi.fn().mockResolvedValue(undefined) })),
    markRunning: vi.fn().mockResolvedValue(undefined),
    heartbeat: vi.fn().mockResolvedValue(undefined),
    finish,
    isCancelled: vi.fn().mockResolvedValue(false),
    ...overrides,
  };
  return { ctx: ctx as never as Parameters<typeof runJob>[1], finish };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  // Le pipeline RENVOIE son issue depuis le 2026-08-21 : « ne pas lever » ne
  // veut pas dire « avoir réussi ». Le défaut du harnais suit ce contrat.
  agentsMock.runOrchestratorPipeline.mockResolvedValue({ ok: true });
});

describe('cycle de vie du run', () => {
  it('marque le run running avant de lancer le pipeline', async () => {
    const { ctx } = makeCtx();
    await runJob(payload, ctx);
    expect((ctx as never as { markRunning: ReturnType<typeof vi.fn> }).markRunning)
      .toHaveBeenCalledWith(payload.runId);
  });

  it('clôt en succeeded quand le pipeline aboutit', async () => {
    const { ctx, finish } = makeCtx();
    await runJob(payload, ctx);
    expect(finish).toHaveBeenCalledWith(payload.runId, 'succeeded');
  });

  it('clôt en cancelled quand le run a été annulé', async () => {
    // Le pipeline s'est terminé sans lever : sans ce contrôle, un run annulé
    // serait compté comme un succès.
    const { ctx, finish } = makeCtx({ isCancelled: vi.fn().mockResolvedValue(true) });
    await runJob(payload, ctx);
    expect(finish).toHaveBeenCalledWith(payload.runId, 'cancelled');
  });
});

describe('échec du pipeline', () => {
  beforeEach(() => {
    agentsMock.runOrchestratorPipeline.mockRejectedValue(new Error('routage injoignable'));
  });

  it('clôt le run en failed avec la cause', async () => {
    const { ctx, finish } = makeCtx();
    await expect(runJob(payload, ctx)).rejects.toThrow('routage injoignable');
    expect(finish).toHaveBeenCalledWith(payload.runId, 'failed', 'routage injoignable');
  });

  it('relaie l échec à BullMQ plutôt que de l avaler', async () => {
    // `attempts: 1` : le job sera marqué échoué, jamais rejoué. Avaler l erreur
    // le ferait passer pour un succès.
    const { ctx } = makeCtx();
    await expect(runJob(payload, ctx)).rejects.toThrow();
  });

  it('n oublie pas de clore même si le journal est en panne', async () => {
    const { ctx, finish } = makeCtx({
      createEventWriter: vi.fn(() => ({
        insert: vi.fn().mockRejectedValue(new Error('journal HS')),
      })),
    });
    await expect(runJob(payload, ctx)).rejects.toThrow();
    expect(finish).toHaveBeenCalledWith(payload.runId, 'failed', expect.any(String));
  });
});

describe('battement de cœur', () => {
  it('bat pendant que le pipeline tourne, et s arrête à la fin', async () => {
    vi.useFakeTimers();
    let releasePipeline: (() => void) | undefined;
    agentsMock.runOrchestratorPipeline.mockImplementation(
      () => new Promise<{ ok: true }>((resolve) => {
        releasePipeline = () => resolve({ ok: true });
      }),
    );

    const { ctx } = makeCtx();
    const heartbeat = (ctx as never as { heartbeat: ReturnType<typeof vi.fn> }).heartbeat;
    const job = runJob(payload, ctx);

    await vi.advanceTimersByTimeAsync(31_000);
    expect(heartbeat).toHaveBeenCalledTimes(1);

    releasePipeline?.();
    await job;

    // Après la fin, plus aucun battement : un intervalle orphelin ferait passer
    // un run mort pour vivant auprès de la réconciliation.
    const afterRun = heartbeat.mock.calls.length;
    await vi.advanceTimersByTimeAsync(120_000);
    expect(heartbeat).toHaveBeenCalledTimes(afterRun);
    vi.useRealTimers();
  });
});

/**
 * Un run dont le DERNIER mot est une erreur ne doit pas compter comme un succès.
 *
 * Le pipeline ne LÈVE pas sur une erreur non liée aux crédits : il l'émet au
 * journal et rend la main — c'est voulu, une erreur métier doit atteindre
 * l'utilisateur sans tuer le porteur. Mais `runJob` en déduisait « succeeded ».
 *
 * Mesuré le 2026-08-21 sur un run RÉEL, base de production, 126 événements :
 *
 *     seq 127  kind=error  « Orchestrator completed in a non-billable state:
 *                            ROUTING_DONE »
 *     pcb_runs.status = 'succeeded'   ← faux
 *
 * Le board n'était ni DRC-clean ni livré, et le dernier message à l'utilisateur
 * était une erreur. Toute réconciliation ou tout tableau de bord lisant
 * `pcb_runs` l'aurait compté comme une réussite.
 */
describe('un run terminé sur une erreur', () => {
  it('est clos en failed, avec la cause', async () => {
    agentsMock.runOrchestratorPipeline.mockResolvedValue({
      ok: false,
      error: 'Orchestrator completed in a non-billable state: ROUTING_DONE',
    });
    const { ctx, finish } = makeCtx();

    await runJob(payload, ctx);

    expect(finish).toHaveBeenCalledWith(
      payload.runId,
      'failed',
      'Orchestrator completed in a non-billable state: ROUTING_DONE',
    );
  });

  it('reste succeeded quand le pipeline aboutit vraiment', async () => {
    agentsMock.runOrchestratorPipeline.mockResolvedValue({ ok: true });
    const { ctx, finish } = makeCtx();

    await runJob(payload, ctx);

    expect(finish).toHaveBeenCalledWith(payload.runId, 'succeeded');
  });

  it('laisse l annulation primer sur l échec', async () => {
    // Un run annulé n'est pas un run raté : l'utilisateur a décidé d'arrêter.
    agentsMock.runOrchestratorPipeline.mockResolvedValue({ ok: false, error: 'peu importe' });
    const { ctx, finish } = makeCtx({ isCancelled: vi.fn().mockResolvedValue(true) });

    await runJob(payload, ctx);

    expect(finish).toHaveBeenCalledWith(payload.runId, 'cancelled');
  });
});
