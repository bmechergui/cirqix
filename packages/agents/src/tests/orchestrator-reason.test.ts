import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Déclenchement DÉTERMINISTE du reasoner.
 *
 * Règle métier à seuil (routed_percent < 100 → rescue) = décision de CODE, pas
 * de jugement LLM. L'orchestrateur lance lui-même call_agent_reason après
 * call_agent_routing si le routage n'est pas complet, et émet l'event SSE
 * `reasoning` pour la visibilité temps-réel (ChatRail). Ces tests prouvent :
 *   - routing 95% → reason auto-déclenché + event reasoning émis
 *   - routing 100% → reason NON déclenché, aucun event reasoning
 */

// Stream Anthropic mocké : une file de "streams" consommée appel par appel.
const hoisted = vi.hoisted(() => ({ streamQueue: [] as unknown[][] }));

vi.mock('@anthropic-ai/sdk', () => ({
  default: class {
    messages = {
      create: async () => {
        const events =
          hoisted.streamQueue.shift() ?? [
            { type: 'message_delta', delta: { stop_reason: 'end_turn' } },
          ];
        return (async function* () {
          for (const e of events) yield e;
        })();
      },
    };
  },
}));

// tools mockés : on contrôle ce que routing/reason renvoient + on espionne les appels.
const toolsMock = vi.hoisted(() => ({
  ACTIVE_PCB_TOOLS: [] as unknown[],
  executeToolStub: vi.fn(),
}));
vi.mock('../tools', () => toolsMock);

import {
  runOrchestrator,
  shouldRescueRouting,
  mergeRescueIntoRouting,
  type SSEEvent,
} from '../orchestrator';

// Sonnet appelle call_agent_routing (un seul tool_use), puis end_turn à l'itération 2.
const ROUTING_TOOL_STREAM = [
  {
    type: 'content_block_start',
    content_block: { type: 'tool_use', id: 'tu_route', name: 'call_agent_routing' },
  },
  { type: 'content_block_delta', delta: { type: 'input_json_delta', partial_json: '{}' } },
  { type: 'content_block_stop' },
  { type: 'message_delta', delta: { stop_reason: 'tool_use' } },
];
const END_STREAM = [{ type: 'message_delta', delta: { stop_reason: 'end_turn' } }];

async function collect(gen: AsyncGenerator<SSEEvent>): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  for await (const e of gen) events.push(e);
  return events;
}

describe('shouldRescueRouting — décision à seuil', () => {
  it('true si routed_percent < 100', () => {
    expect(shouldRescueRouting({ routed_percent: 95 })).toBe(true);
    expect(shouldRescueRouting({ routed_percent: 0 })).toBe(true);
  });
  it('false si 100% ou champ absent/non numérique', () => {
    expect(shouldRescueRouting({ routed_percent: 100 })).toBe(false);
    expect(shouldRescueRouting({})).toBe(false);
    expect(shouldRescueRouting({ routed_percent: 'x' })).toBe(false);
  });
});

describe('mergeRescueIntoRouting — fusion du résultat reasoner dans le routage', () => {
  it('reprend le pct + board du reasoner et concatène la note', () => {
    const merged = mergeRescueIntoRouting(
      { routed_percent: 95, kicad_pcb_content: 'OLD', note: 'routing 95%' },
      { routed_percent: 100, kicad_pcb_content: 'NEW', reasoning_steps: ['a'], note: 'reason 100%' },
    );
    expect(merged['routed_percent']).toBe(100);
    expect(merged['kicad_pcb_content']).toBe('NEW');
    expect(String(merged['note'])).toContain('Reasoner');
  });

  it('ne régresse JAMAIS : reasoner indisponible (0%) → routage préservé', () => {
    const merged = mergeRescueIntoRouting(
      { routed_percent: 95, kicad_pcb_content: 'OLD', note: 'routing 95%' },
      { routed_percent: 0, reasoning_steps: [], note: 'service indisponible' }, // pas de board
    );
    expect(merged['routed_percent']).toBe(95);
    expect(merged['kicad_pcb_content']).toBe('OLD');
  });
});

describe('orchestrator — déclenchement déterministe du reasoner', () => {
  beforeEach(() => {
    process.env['ANTHROPIC_API_KEY'] = 'test-key';
    hoisted.streamQueue.length = 0;
    toolsMock.executeToolStub.mockReset();
  });

  it('lance call_agent_reason automatiquement quand routing < 100%', async () => {
    hoisted.streamQueue.push([...ROUTING_TOOL_STREAM], [...END_STREAM]);
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_routing')
        return { status: 'success', pcb_status: 'ROUTING_DONE', routed_percent: 95, kicad_pcb_content: 'PCB', note: 'routing 95%' };
      if (name === 'call_agent_reason')
        return { status: 'success', pcb_status: 'ROUTING_DONE', routed_percent: 100, reasoning_steps: ['✓ Route NET', '✓ Routage complet'], kicad_pcb_content: 'PCB2', note: 'reason 100%' };
      return {};
    });

    const events = await collect(
      runOrchestrator({ userMessage: 'route it', projectId: 'p1', history: [] }),
    );

    const calledNames = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calledNames).toContain('call_agent_reason');

    const reasoning = events.find((e): e is Extract<SSEEvent, { type: 'reasoning' }> => e.type === 'reasoning');
    expect(reasoning).toBeDefined();
    expect(reasoning?.steps).toContain('✓ Routage complet');
  });

  it('ne lance PAS call_agent_reason quand routing = 100%', async () => {
    hoisted.streamQueue.push([...ROUTING_TOOL_STREAM], [...END_STREAM]);
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_routing')
        return { status: 'success', pcb_status: 'ROUTING_DONE', routed_percent: 100, kicad_pcb_content: 'PCB', note: 'routing 100%' };
      return {};
    });

    const events = await collect(
      runOrchestrator({ userMessage: 'route it', projectId: 'p1', history: [] }),
    );

    const calledNames = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calledNames).not.toContain('call_agent_reason');
    expect(events.find((e) => e.type === 'reasoning')).toBeUndefined();
  });
});
