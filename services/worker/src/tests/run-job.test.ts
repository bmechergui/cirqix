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
  agentsMock.runOrchestratorPipeline.mockResolvedValue(undefined);
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
      () => new Promise<void>((resolve) => {
        releasePipeline = resolve;
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
