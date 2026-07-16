import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Retry de placement DÉTERMINISTE.
 *
 * Mesuré 2026-07-14 (examples/stm32-validation, juge kicad-cli pcb drc) : le
 * plancher 91% observé sur placement frais est un artefact du tirage GA — le
 * MÊME code route 100% sur un placement favorable (benchmark B1). Règle métier
 * à seuil : si après routage + reasoner le board reste <100%, l'orchestrateur
 * relance LUI-MÊME placement (nouveau tirage) puis routage, max
 * MAX_PLACEMENT_ATTEMPTS tentatives au total, en conservant le MEILLEUR
 * résultat (anti-régression). Décision de CODE, pas de jugement Sonnet.
 */

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

const toolsMock = vi.hoisted(() => ({
  ACTIVE_PCB_TOOLS: [] as unknown[],
  executeToolStub: vi.fn(),
}));
vi.mock('../tools', () => toolsMock);

import {
  runOrchestrator,
  shouldRetryPlacement,
  keepBestRouting,
  MAX_PLACEMENT_ATTEMPTS,
  type SSEEvent,
} from '../orchestrator';

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

describe('shouldRetryPlacement — décision à seuil', () => {
  it('true si <100% et budget de tentatives restant', () => {
    expect(shouldRetryPlacement({ routed_percent: 91 }, 1)).toBe(true);
    expect(shouldRetryPlacement({ routed_percent: 0 }, 2)).toBe(true);
  });
  it('false à 100%, au plafond de tentatives, ou champ absent', () => {
    expect(shouldRetryPlacement({ routed_percent: 100 }, 1)).toBe(false);
    expect(shouldRetryPlacement({ routed_percent: 91 }, MAX_PLACEMENT_ATTEMPTS)).toBe(false);
    expect(shouldRetryPlacement({}, 1)).toBe(false);
    expect(shouldRetryPlacement({ routed_percent: 'x' }, 1)).toBe(false);
  });
});

describe('keepBestRouting — anti-régression', () => {
  it('garde le candidat s’il est meilleur', () => {
    const best = keepBestRouting({ routed_percent: 91 }, { routed_percent: 100 });
    expect(best['routed_percent']).toBe(100);
  });
  it('conserve le meilleur existant sinon', () => {
    const best = keepBestRouting(
      { routed_percent: 91, kicad_pcb_content: 'BEST' },
      { routed_percent: 82, kicad_pcb_content: 'WORSE' },
    );
    expect(best['routed_percent']).toBe(91);
    expect(best['kicad_pcb_content']).toBe('BEST');
  });
});

describe('orchestrator — retry placement déterministe', () => {
  beforeEach(() => {
    process.env['ANTHROPIC_API_KEY'] = 'test-key';
    hoisted.streamQueue.length = 0;
    toolsMock.executeToolStub.mockReset();
  });

  it('re-place et re-route quand routing+reasoner restent <100%, puis s’arrête à 100%', async () => {
    hoisted.streamQueue.push([...ROUTING_TOOL_STREAM], [...END_STREAM]);
    let routingCalls = 0;
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_routing') {
        routingCalls++;
        // 1er tirage : 91% ; 2e tirage (après re-placement) : 100%.
        return routingCalls === 1
          ? { status: 'success', routed_percent: 91, kicad_pcb_content: 'PCB1', note: 'routing 91%' }
          : { status: 'success', routed_percent: 100, kicad_pcb_content: 'PCB2', note: 'routing 100%' };
      }
      if (name === 'call_agent_reason')
        return { status: 'success', routed_percent: 91, reasoning_steps: [], note: 'reason 91%' };
      if (name === 'call_agent_placement')
        return { status: 'success', placed_count: 17, note: 'placement (nouveau tirage)' };
      return {};
    });

    await collect(runOrchestrator({ userMessage: 'route', projectId: 'p1', history: [] }));

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls.filter((n) => n === 'call_agent_placement')).toHaveLength(1);
    expect(calls.filter((n) => n === 'call_agent_routing')).toHaveLength(2);
  });

  it('respecte le plafond de tentatives et conserve le meilleur résultat', async () => {
    hoisted.streamQueue.push([...ROUTING_TOOL_STREAM], [...END_STREAM]);
    const pcts = [91, 82, 82]; // tirages successifs — jamais 100%
    let routingCalls = 0;
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_routing') {
        const pct = pcts[Math.min(routingCalls, pcts.length - 1)];
        routingCalls++;
        return { status: 'success', routed_percent: pct, kicad_pcb_content: `PCB${routingCalls}`, note: `routing ${pct}%` };
      }
      if (name === 'call_agent_reason')
        return { status: 'success', routed_percent: 0, reasoning_steps: [], note: 'reasoner indisponible' };
      if (name === 'call_agent_placement')
        return { status: 'success', placed_count: 17, note: 'placement' };
      return {};
    });

    const events = await collect(
      runOrchestrator({ userMessage: 'route', projectId: 'p1', history: [] }),
    );

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    // MAX_PLACEMENT_ATTEMPTS tentatives au total = MAX-1 re-placements.
    expect(calls.filter((n) => n === 'call_agent_placement')).toHaveLength(MAX_PLACEMENT_ATTEMPTS - 1);
    expect(calls.filter((n) => n === 'call_agent_routing')).toHaveLength(MAX_PLACEMENT_ATTEMPTS);

    // Anti-régression : le pcb_state final du routage reflète le MEILLEUR (91%).
    const states = events.filter(
      (e): e is Extract<SSEEvent, { type: 'pcb_state' }> => e.type === 'pcb_state',
    );
    const last = states[states.length - 1];
    expect(last?.state['routed_percent']).toBe(91);
  });

  it('ne re-place PAS quand le routage atteint 100% directement', async () => {
    hoisted.streamQueue.push([...ROUTING_TOOL_STREAM], [...END_STREAM]);
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_routing')
        return { status: 'success', routed_percent: 100, kicad_pcb_content: 'PCB', note: 'routing 100%' };
      return {};
    });

    await collect(runOrchestrator({ userMessage: 'route', projectId: 'p1', history: [] }));

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls).not.toContain('call_agent_placement');
  });
});
