import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleReason — sauvetage de routage, déclenché DÉTERMINISTIQUEMENT par
 * l'orchestrateur quand routed_percent < 100 (jamais par Sonnet).
 *
 * Contrairement aux autres handlers, celui-ci est sûr par construction et n'a
 * PAS été modifié : `runReasoner` n'échoue jamais (il intercepte fetch/non-2xx et
 * renvoie {routedPercent: 0}), et l'anti-régression de mergeRescueIntoRouting
 * empêche un reasoner en échec de dégrader un routage existant. Ces tests
 * verrouillent ces deux propriétés — c'est précisément parce qu'elles sont
 * implicites qu'elles méritent d'être explicitées.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const reasoningMock = vi.hoisted(() => ({ runReasoner: vi.fn() }));
vi.mock('../engines/reasoning-service', () => reasoningMock);

import { handleReason } from '../tools/handlers/reason';
import { mergeRescueIntoRouting } from '../orchestrator';
import { pcbStateCache } from '../tools/shared';

const PCB = '(kicad_pcb (net 1 "GND"))';
const UNBLOCKED_PCB = '(kicad_pcb (net 1 "GND") (rescued yes))';
const PROJECT = 'p1';

function reasonerResult(overrides: Record<string, unknown> = {}) {
  return {
    kicadPcbContent: UNBLOCKED_PCB,
    routedPercent: 100,
    steps: ['Déplace C12 près de U1', 'Reroute NET-VCC'],
    usedLlm: true,
    ...overrides,
  };
}

beforeEach(() => {
  pcbStateCache.clear();
  reasoningMock.runReasoner.mockReset();
  reasoningMock.runReasoner.mockResolvedValue(reasonerResult());
});

function seedCache(kicadPcbContent: string | undefined = PCB) {
  pcbStateCache.set(PROJECT, {
    schema: { components: [{ ref: 'U1' }], nets: [{ name: 'VCC' }] },
    boardW: 50,
    boardH: 40,
    kicad_pcb_content: kicadPcbContent,
  } as never);
}

describe('sauvetage nominal', () => {
  it('propage le pourcentage relevé et les actions du reasoner', async () => {
    seedCache();

    const result = await handleReason(PROJECT);

    expect(result['routed_percent']).toBe(100);
    expect(result['reasoning_steps']).toEqual([
      'Déplace C12 près de U1',
      'Reroute NET-VCC',
    ]);
  });

  it('persiste le board débloqué en cache pour le DRC', async () => {
    seedCache();

    await handleReason(PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe(UNBLOCKED_PCB);
  });

  it.each([
    [true, 'reasoner-llm'],
    [false, 'reasoner-heuristic'],
  ])('usedLlm=%s → engine %s', async (usedLlm, expected) => {
    seedCache();
    reasoningMock.runReasoner.mockResolvedValue(reasonerResult({ usedLlm }));

    const result = await handleReason(PROJECT);

    expect(result['engine']).toBe(expected);
  });

  it('conserve le board d’origine quand le reasoner n’en renvoie pas', async () => {
    seedCache();
    reasoningMock.runReasoner.mockResolvedValue(
      reasonerResult({ kicadPcbContent: undefined, routedPercent: 91 }),
    );

    const result = await handleReason(PROJECT);

    expect(result['kicad_pcb_content']).toBe(PCB);
    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe(PCB);
  });
});

describe('reasoner indisponible', () => {
  it('cache vide → saute proprement sans appeler le service', async () => {
    const result = await handleReason(PROJECT);

    expect(result['routed_percent']).toBe(0);
    expect(result['engine']).toBe('fallback-skip');
    expect(reasoningMock.runReasoner).not.toHaveBeenCalled();
  });

  it('remonte le warning du service et un pourcentage honnête', async () => {
    seedCache();
    reasoningMock.runReasoner.mockResolvedValue({
      routedPercent: 0,
      steps: [],
      usedLlm: false,
      warning: 'fetch failed',
    });

    const result = await handleReason(PROJECT);

    expect(result['routed_percent']).toBe(0);
    expect(result['warning']).toBe('fetch failed');
  });

  /**
   * L'invariant qui compte vraiment : un reasoner en échec ne doit JAMAIS
   * dégrader un routage déjà obtenu. handleReason renvoie toujours un
   * kicad_pcb_content (repli sur le board d'entrée) — c'est la comparaison de
   * pourcentage de mergeRescueIntoRouting qui protège, pas l'absence de board.
   */
  it('un reasoner à 0% ne dégrade pas un routage à 91%', async () => {
    seedCache();
    reasoningMock.runReasoner.mockResolvedValue({
      routedPercent: 0,
      steps: [],
      usedLlm: false,
      warning: 'fetch failed',
    });

    const reason = await handleReason(PROJECT);
    const merged = mergeRescueIntoRouting(
      { routed_percent: 91, kicad_pcb_content: 'ROUTED_91', note: 'routing 91%' },
      reason,
    );

    expect(merged['routed_percent']).toBe(91);
    expect(merged['kicad_pcb_content']).toBe('ROUTED_91');
  });

  it('un reasoner qui améliore à 100% remplace bien le routage', async () => {
    seedCache();

    const reason = await handleReason(PROJECT);
    const merged = mergeRescueIntoRouting(
      { routed_percent: 91, kicad_pcb_content: 'ROUTED_91', note: 'routing 91%' },
      reason,
    );

    expect(merged['routed_percent']).toBe(100);
    expect(merged['kicad_pcb_content']).toBe(UNBLOCKED_PCB);
  });
});
