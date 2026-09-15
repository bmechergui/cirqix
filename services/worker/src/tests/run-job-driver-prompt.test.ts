import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Un run de provenance `driver` SANS schéma passe par le porteur du driver
 * avec la description : `call_agent_schema` la confie au fournisseur
 * configuré (D-2026-09-13-a). Un run `orchestrator` sans schéma garde
 * l'orchestrateur — la provenance vient de `pcb_runs`, jamais du payload.
 */
const agentsMock = vi.hoisted(() => ({
  runOrchestratorPipeline: vi.fn(),
  runDriver: vi.fn(),
  PgSink: class {
    constructor(public runId: string, public writer: { insert: (rows: unknown[]) => Promise<void> }) {}
    async emit(): Promise<void> {}
    async close(): Promise<void> {}
  },
  TranscriptSink: class {
    constructor(public inner: { emit: (ev: unknown) => Promise<void> }) {}
    async emit(ev: unknown): Promise<void> {
      await this.inner.emit(ev);
    }
    transcript(): string {
      return '';
    }
  },
}));
vi.mock('@cirqix/agents', () => agentsMock);
vi.mock('@cirqix/logger', () => ({
  logger: { child: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
}));

import { runJob } from '../run-job.js';

const payload = {
  runId: '11111111-1111-4111-8111-111111111111',
  projectId: '22222222-2222-4222-8222-222222222222',
  userId: '33333333-3333-4333-8333-333333333333',
  prompt: 'un clignotant NE555',
  iterationStart: 0,
};

function ctxAvec(agentMode: string) {
  return {
    supabase: {} as never,
    createStore: vi.fn(() => ({}) as never),
    readAgentMode: vi.fn().mockResolvedValue(agentMode),
    createEventWriter: vi.fn(() => ({ insert: vi.fn().mockResolvedValue(undefined) })),
    chatMessages: { append: vi.fn().mockResolvedValue(false) },
    markRunning: vi.fn().mockResolvedValue(undefined),
    heartbeat: vi.fn().mockResolvedValue(undefined),
    finish: vi.fn().mockResolvedValue(undefined),
    isCancelled: vi.fn().mockResolvedValue(false),
  } as never as Parameters<typeof runJob>[1];
}

beforeEach(() => {
  vi.clearAllMocks();
  agentsMock.runOrchestratorPipeline.mockResolvedValue({ ok: true });
  agentsMock.runDriver.mockReturnValue('porteur-driver');
});

describe('runJob — provenance driver sans schéma', () => {
  it('confie la description au porteur du driver', async () => {
    await runJob(payload, ctxAvec('driver'));
    expect(agentsMock.runDriver).toHaveBeenCalledWith({ prompt: payload.prompt, projectId: payload.projectId });
    const opts = agentsMock.runOrchestratorPipeline.mock.calls[0]![0] as { source?: unknown };
    expect(opts.source).toBe('porteur-driver');
  });

  it('un run orchestrator sans schéma garde l orchestrateur', async () => {
    await runJob(payload, ctxAvec('orchestrator'));
    expect(agentsMock.runDriver).not.toHaveBeenCalled();
    const opts = agentsMock.runOrchestratorPipeline.mock.calls[0]![0] as { source?: unknown };
    expect(opts.source).toBeUndefined();
  });

  it('un schéma fourni passe au porteur quelle que soit la provenance', async () => {
    const schema = { components: [{ ref: 'R1' }], nets: ['GND'] };
    await runJob({ ...payload, schema }, ctxAvec('driver'));
    expect(agentsMock.runDriver).toHaveBeenCalledWith({ schema, projectId: payload.projectId });
  });
});
