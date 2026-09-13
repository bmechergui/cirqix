import { describe, it, expect, vi } from 'vitest';

/**
 * Un pipeline qui s arrete sur une erreur SANS `done` a ECHOUE.
 *
 * Mesure du 2026-09-13, run 0525dc97 : la chaine du driver s est arretee au
 * SCHEMA (`call_agent_schema` en erreur), l evenement `error` a ete relaye au
 * journal, et le worker a marque le run `succeeded` — `runOrchestratorPipeline`
 * rendait `ok: true` des lors que rien n avait leve.
 */
vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});
vi.mock('../orchestrator', () => ({ runOrchestrator: vi.fn() }));

import { runOrchestratorPipeline } from '../pipeline/run-orchestrator';
import type { SSEEvent } from '../orchestrator';

function faux() {
  const emis: unknown[] = [];
  const sink = { emit: async (e: unknown) => { emis.push(e); }, close: async () => {} };
  // Un magasin qui accepte tout : l issue ne depend pas de la persistance.
  const store = new Proxy({}, { get: () => async () => undefined });
  return { emis, sink: sink as never, store: store as never };
}
async function* source(evs: SSEEvent[]): AsyncGenerator<SSEEvent> {
  for (const e of evs) yield e;
}

describe('runOrchestratorPipeline — issue', () => {
  it('une erreur sans done : le run a ECHOUE, avec le message', async () => {
    const { sink, store } = faux();
    const issue = await runOrchestratorPipeline({
      sink, store, projectId: 'p', prompt: 'x', iterationStart: 0,
      source: source([{ type: 'step', step: 'SCHEMA' }, { type: 'error', message: 'Schema generation failed — claude-code' }]),
    });
    expect(issue).toEqual({ ok: false, error: 'Schema generation failed — claude-code' });
  });

  it('une source vide (ni erreur ni done) reste un succes, comme avant', async () => {
    const { sink, store } = faux();
    const issue = await runOrchestratorPipeline({ sink, store, projectId: 'p', prompt: 'x', iterationStart: 0, source: source([]) });
    expect(issue).toEqual({ ok: true });
  });
});
