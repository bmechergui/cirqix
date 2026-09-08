import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleReason — sauvetage de routage, déclenché DÉTERMINISTIQUEMENT par
 * l'orchestrateur quand routed_percent < 100 (jamais par Sonnet).
 *
 * Deux proprietes le rendent sur : `runReasoner` n'echoue jamais (il intercepte
 * fetch/non-2xx et renvoie {routedPercent: 0}), et l'anti-regression de
 * `mergeRescueIntoRouting` empeche un reasoner en echec de degrader un routage
 * existant. Ces tests les verrouillent — c'est precisement parce qu'elles sont
 * implicites qu'elles meritent d'etre explicitees.
 *
 * ⚠️ Cet en-tete a longtemps affirme que ce handler « n'a PAS ete modifie » et
 * qu'il etait « sur par construction ». C'etait faux sur un point, releve le
 * 2026-09-07 : sans board en cache il rendait `status:'success'` ET promouvait
 * `pcb_status:'ROUTING_DONE'`, que `orchestrator-bridge` persiste dans
 * `projects.status`. Il etait le SEUL des huit a ne pas avoir recu le correctif
 * fail-fast du 2026-07-27.
 *
 * La branche etait inatteignable — `shouldRescueRouting` exige un routage
 * reussi, qui a lui-meme ecrit le cache — mais « inatteignable aujourd'hui »
 * n'est pas une garantie, c'est une coincidence. Elle est fermee.
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
  it('cache vide → ECHOUE FERME, sans promouvoir de statut', async () => {
    // ⚠️ Ce handler etait le SEUL des huit a ne pas avoir recu le correctif
    // fail-fast du 2026-07-27. Sans board en cache il rendait
    // `status:'success'` ET `pcb_status:'ROUTING_DONE'` — or
    // `orchestrator-bridge` persiste `pcb_status` dans `projects.status`.
    // Un projet pouvait donc etre marque ROUTING_DONE sans qu aucun board
    // n existe.
    //
    // La branche est aujourd hui inatteignable — `shouldRescueRouting` exige
    // un `routed_percent` numerique, donc un routage REUSSI, qui a lui-meme
    // ecrit le cache. Elle est a un changement de declencheur pres de
    // s ouvrir, et la fermer coute trois lignes.
    const result = await handleReason(PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).toBeUndefined();
    expect(reasoningMock.runReasoner).not.toHaveBeenCalled();
  });

  it('son echec ne degrade PAS le routage deja obtenu', async () => {
    // La garde de fusion doit continuer de tenir avec un resultat en erreur :
    // « le reasoner ne peut qu AMELIORER ».
    const routage = {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: 95,
      kicad_pcb_content: PCB,
      note: 'routage',
    };
    const fusion = mergeRescueIntoRouting(routage, await handleReason(PROJECT));

    expect(fusion['routed_percent']).toBe(95);
    expect(fusion['kicad_pcb_content']).toBe(PCB);
    expect(fusion['status']).toBe('success');
    expect(fusion['pcb_status']).toBe('ROUTING_DONE');
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
