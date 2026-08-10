import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * Retry placement piloté par le DRC.
 *
 * Le re-tirage déterministe existait déjà (`shouldRetryPlacement`) mais n'était
 * armé que par `routed_percent < 100`. Or un board peut être routé à 100 % ET
 * refusé par le DRC : mesuré le 2026-07-27 sur
 * `examples/led-blinker-full-pipeline`, 3 runs à 100 % routé donnent 0, 12 et 4
 * violations selon le tirage GA — soit 2 boards livrables sur 3, le troisième
 * n'étant qu'un mauvais tirage. Le placement étant stochastique et sans seed,
 * re-tirer est le levier déterministe, exactement comme pour le routage.
 *
 * Invariant d'anti-régression : on conserve TOUJOURS le meilleur board
 * rencontré — un re-tirage ne peut jamais dégrader le résultat.
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
  shouldRetryForDrc,
  keepBestDrc,
  MAX_DRC_ATTEMPTS,
  type SSEEvent,
} from '../orchestrator';
import { pcbStateCache } from '../tools/shared';

const DRC_TOOL_STREAM = [
  {
    type: 'content_block_start',
    content_block: { type: 'tool_use', id: 'tu_drc', name: 'call_agent_drc' },
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

describe('shouldRetryForDrc — décision à seuil', () => {
  it('re-tire tant que le DRC n’est pas clean et que le budget reste', () => {
    expect(shouldRetryForDrc({ drc_clean: false, drcViolations: [1] }, 1)).toBe(true);
  });

  it('s’arrête dès que le board est clean', () => {
    expect(shouldRetryForDrc({ drc_clean: true }, 1)).toBe(false);
  });

  it('s’arrête au plafond de tentatives', () => {
    expect(shouldRetryForDrc({ drc_clean: false }, MAX_DRC_ATTEMPTS)).toBe(false);
  });

  it('ne re-tire PAS sur une erreur de service — re-placer ne répare pas un Docker éteint', () => {
    expect(shouldRetryForDrc({ status: 'error', error: 'KICAD_SERVICE_URL' }, 1)).toBe(false);
  });
});

describe('keepBestDrc — anti-régression', () => {
  it('un board clean bat un board non clean', () => {
    const best = keepBestDrc(
      { drc_clean: false, drcViolations: [1, 2] },
      { drc_clean: true, drcViolations: [] },
    );
    expect(best['drc_clean']).toBe(true);
  });

  it('à égalité de propreté, garde celui qui a le moins de violations', () => {
    const best = keepBestDrc(
      { drc_clean: false, drcViolations: [1, 2, 3], kicad_pcb_content: 'PIRE' },
      { drc_clean: false, drcViolations: [1], kicad_pcb_content: 'MIEUX' },
    );
    expect(best['kicad_pcb_content']).toBe('MIEUX');
  });

  it('ne remplace JAMAIS un board clean par un board sale', () => {
    const best = keepBestDrc(
      { drc_clean: true, drcViolations: [], kicad_pcb_content: 'CLEAN' },
      { drc_clean: false, drcViolations: [], kicad_pcb_content: 'SALE' },
    );
    expect(best['kicad_pcb_content']).toBe('CLEAN');
  });
});

describe('orchestrateur — re-tirage piloté par le DRC', () => {
  beforeEach(() => {
    process.env['ANTHROPIC_API_KEY'] = 'test-key';
    hoisted.streamQueue.length = 0;
    toolsMock.executeToolStub.mockReset();
    pcbStateCache.clear();
  });

  it('re-place, re-route et re-DRC jusqu’à obtenir un board clean', async () => {
    hoisted.streamQueue.push([...DRC_TOOL_STREAM], [...END_STREAM]);
    let drcCalls = 0;
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_drc') {
        drcCalls++;
        // 1er tirage sale, 2e propre — exactement le profil mesuré.
        return drcCalls === 1
          ? { status: 'success', drc_clean: false, drcViolations: [1, 2], note: 'DRC 2 violations' }
          : { status: 'success', drc_clean: true, drcViolations: [], note: 'DRC OK' };
      }
      if (name === 'call_agent_routing')
        return { status: 'success', routed_percent: 100, note: 'routing 100%' };
      if (name === 'call_agent_placement')
        return { status: 'success', placed_count: 8, note: 'placement' };
      return {};
    });

    const events = await collect(
      runOrchestrator({ userMessage: 'fabrique', projectId: 'p1', history: [] }),
    );

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls.filter((n) => n === 'call_agent_placement')).toHaveLength(1);
    expect(calls.filter((n) => n === 'call_agent_drc')).toHaveLength(2);

    const states = events.filter(
      (e): e is Extract<SSEEvent, { type: 'pcb_state' }> => e.type === 'pcb_state',
    );
    expect(states[states.length - 1]?.state['drc_clean']).toBe(true);
  });

  it('respecte le plafond et conserve le MEILLEUR board si aucun n’est clean', async () => {
    hoisted.streamQueue.push([...DRC_TOOL_STREAM], [...END_STREAM]);
    const counts = [5, 1, 9]; // tirages successifs — jamais clean
    let drcCalls = 0;
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_drc') {
        const n = counts[Math.min(drcCalls, counts.length - 1)] ?? 9;
        drcCalls++;
        const content = `PCB${n}`;
        // Simule handleDrc : chaque tentative écrase le cache avec SON board.
        pcbStateCache.set('p1', {
          schema: { components: [], nets: [] },
          boardW: 50,
          boardH: 40,
          kicad_pcb_content: content,
          drc_clean: false,
        });
        return {
          status: 'success',
          drc_clean: false,
          drcViolations: Array.from({ length: n }, (_, i) => i),
          kicad_pcb_content: content,
          note: `DRC ${n} violations`,
        };
      }
      if (name === 'call_agent_routing')
        return { status: 'success', routed_percent: 100, note: 'routing' };
      if (name === 'call_agent_placement')
        return { status: 'success', placed_count: 8, note: 'placement' };
      return {};
    });

    const events = await collect(
      runOrchestrator({ userMessage: 'fabrique', projectId: 'p1', history: [] }),
    );

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls.filter((n) => n === 'call_agent_drc')).toHaveLength(MAX_DRC_ATTEMPTS);

    // Le meilleur tirage (1 violation) doit être celui retenu.
    const states = events.filter(
      (e): e is Extract<SSEEvent, { type: 'pcb_state' }> => e.type === 'pcb_state',
    );
    expect(states[states.length - 1]?.state['kicad_pcb_content']).toBe('PCB1');
    // Correctif B : le cache (lu par handleExport) doit coller au board retenu,
    // pas au dernier essai (PCB9, 9 violations).
    expect(pcbStateCache.get('p1')?.kicad_pcb_content).toBe('PCB1');
  });

  it('ne re-place PAS quand le DRC est clean du premier coup', async () => {
    hoisted.streamQueue.push([...DRC_TOOL_STREAM], [...END_STREAM]);
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_drc')
        return { status: 'success', drc_clean: true, drcViolations: [], note: 'DRC OK' };
      return {};
    });

    await collect(runOrchestrator({ userMessage: 'fabrique', projectId: 'p1', history: [] }));

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls).not.toContain('call_agent_placement');
  });

  it('ne re-place PAS quand le service DRC est en erreur', async () => {
    hoisted.streamQueue.push([...DRC_TOOL_STREAM], [...END_STREAM]);
    toolsMock.executeToolStub.mockImplementation(async (name: string) => {
      if (name === 'call_agent_drc')
        return { status: 'error', error: 'kicad-cli indisponible', note: 'DRC impossible' };
      return {};
    });

    await collect(runOrchestrator({ userMessage: 'fabrique', projectId: 'p1', history: [] }));

    const calls = toolsMock.executeToolStub.mock.calls.map((c) => c[0]);
    expect(calls).not.toContain('call_agent_placement');
  });
});
