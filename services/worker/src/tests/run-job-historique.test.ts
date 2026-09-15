import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Le worker consigne la réponse de l'agent dans l'historique du projet.
 *
 * C'est la raison de l'écrire CÔTÉ SERVEUR : un run asynchrone dure jusqu'à
 * 20 minutes, et l'utilisateur ferme son onglet. Si seul le navigateur
 * enregistrait la réponse, elle serait perdue précisément dans ce cas.
 */

const agentsMock = vi.hoisted(() => {
  class PgSink {
    constructor(public runId: string, public writer: unknown) {}
    async emit(): Promise<void> {}
    async close(): Promise<void> {}
  }
  // Le vrai TranscriptSink, recopié en miniature : il accumule le texte visible.
  class TranscriptSink {
    private text = '';
    constructor(private readonly inner: { emit: (ev: unknown) => Promise<void> }) {}
    async emit(ev: { type: string; content?: string; message?: string }): Promise<void> {
      if (ev.type === 'token' && ev.content) this.text += ev.content;
      if (ev.type === 'error' && ev.message) this.text += `\n\n_Error: ${ev.message}_`;
      await this.inner.emit(ev);
    }
    transcript(): string {
      return this.text;
    }
  }
  return { runOrchestratorPipeline: vi.fn(), runDriver: vi.fn(), PgSink, TranscriptSink };
});
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

function makeCtx(agentMode: string | null = 'orchestrator') {
  const append = vi.fn().mockResolvedValue(true);
  const ctx = {
    supabase: {} as never,
    createStore: vi.fn(() => ({}) as never),
    readAgentMode: vi.fn().mockResolvedValue(agentMode),
    createEventWriter: vi.fn(() => ({ insert: vi.fn().mockResolvedValue(undefined) })),
    chatMessages: { append },
    markRunning: vi.fn().mockResolvedValue(undefined),
    heartbeat: vi.fn().mockResolvedValue(undefined),
    finish: vi.fn().mockResolvedValue(undefined),
    isCancelled: vi.fn().mockResolvedValue(false),
  };
  return { ctx: ctx as never as Parameters<typeof runJob>[1], append };
}

type EmitOpts = { sink: { emit: (ev: unknown) => Promise<void> } };

beforeEach(() => {
  vi.clearAllMocks();
});

describe('runJob — historique de discussion', () => {
  it('consigne la réponse de l’agent à la fin du run', async () => {
    agentsMock.runOrchestratorPipeline.mockImplementation(async ({ sink }: EmitOpts) => {
      await sink.emit({ type: 'token', content: 'PCB livré.' });
      await sink.emit({ type: 'done' });
      return { ok: true };
    });
    const { ctx, append } = makeCtx();

    await runJob(payload, ctx);

    expect(append).toHaveBeenCalledWith({
      projectId: payload.projectId,
      userId: payload.userId,
      role: 'assistant',
      content: 'PCB livré.',
    });
  });

  it('consigne aussi l’erreur d’un run qui lève', async () => {
    agentsMock.runOrchestratorPipeline.mockImplementation(async ({ sink }: EmitOpts) => {
      await sink.emit({ type: 'token', content: 'Routage…' });
      throw new Error('routage injoignable');
    });
    const { ctx, append } = makeCtx();

    await expect(runJob(payload, ctx)).rejects.toThrow('routage injoignable');

    expect(append).toHaveBeenCalledWith(
      expect.objectContaining({ role: 'assistant', content: 'Routage…\n\n_Error: routage injoignable_' }),
    );
  });

  it('n’écrit rien quand la provenance est introuvable — aucun run n’a eu lieu', async () => {
    const { ctx, append } = makeCtx(null);
    await runJob(payload, ctx);
    expect(append).not.toHaveBeenCalled();
  });
});
