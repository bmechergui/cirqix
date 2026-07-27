import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleRouting — le handler qui produit le `routed_percent` pilotant TOUTE la
 * mécanique déterministe de l'orchestrateur (shouldRescueRouting /
 * shouldRetryPlacement). Un pourcentage mal propagé rend les deux triggers
 * silencieusement inopérants : le board sort « ROUTING_DONE » sans avoir été
 * secouru ni re-tiré.
 *
 * Les helpers de chaîne (stripTrackSegments / addGroundPlane) ne sont PAS mockés
 * — ce sont des fonctions pures et leur intégration réelle fait partie du contrat.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const engineMock = vi.hoisted(() => ({ runPCBEngine: vi.fn() }));
vi.mock('../engines/engine-router', () => engineMock);

const routingMock = vi.hoisted(() => {
  class RoutingServiceUnavailableError extends Error {}
  return { runRealRouting: vi.fn(), RoutingServiceUnavailableError };
});
vi.mock('../engines/routing-service', () => routingMock);

import { handleRouting } from '../tools/handlers/routing';
import { pcbStateCache } from '../tools/shared';

/** PCB minimal : un net GND (requis par addGroundPlane) + une piste TS à stripper. */
const PCB_WITH_TRACK = [
  '(kicad_pcb',
  '  (net 1 "GND")',
  '  (segment (start 1 1) (end 2 2) (width 0.25) (layer "F.Cu") (net 1))',
  ')',
].join('\n');

const ROUTED_PCB = ['(kicad_pcb', '  (net 1 "GND")', ')'].join('\n');

function schemaOf(componentCount: number, netCount: number) {
  return {
    components: Array.from({ length: componentCount }, (_, i) => ({ ref: `R${i}` })),
    nets: Array.from({ length: netCount }, (_, i) => ({ name: `N${i}` })),
  };
}

function serviceResult(overrides: Record<string, unknown> = {}) {
  return {
    skipped: false,
    kicadPcbContent: ROUTED_PCB,
    routedPercent: 100,
    layers: 2,
    viaCount: 4,
    trackLengthMm: 120,
    ...overrides,
  };
}

const PROJECT = 'p1';

beforeEach(() => {
  pcbStateCache.clear();
  engineMock.runPCBEngine.mockReset();
  engineMock.runPCBEngine.mockResolvedValue({ kicad_pcb_content: PCB_WITH_TRACK });
  routingMock.runRealRouting.mockReset();
  routingMock.runRealRouting.mockResolvedValue(serviceResult());
});

function seedCache(overrides: Record<string, unknown> = {}) {
  pcbStateCache.set(PROJECT, {
    schema: schemaOf(5, 5),
    boardW: 50,
    boardH: 40,
    ...overrides,
  } as never);
}

describe('propagation du routed_percent réel', () => {
  it.each([0, 43, 73, 91, 99, 100])(
    'remonte %i%% tel quel — jamais un 100 arbitraire',
    async (pct) => {
      seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
      routingMock.runRealRouting.mockResolvedValue(serviceResult({ routedPercent: pct }));

      const result = await handleRouting(PROJECT);

      expect(result['routed_percent']).toBe(pct);
      expect(result['engine']).toBe('kicad-tools');
    },
  );

  it('annonce le déclenchement du reasoner dans la note quand <100%', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockResolvedValue(serviceResult({ routedPercent: 73 }));

    const result = await handleRouting(PROJECT);

    expect(String(result['note'])).toContain('reasoner');
  });

  it('n’annonce pas le reasoner à 100%', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    const result = await handleRouting(PROJECT);

    expect(String(result['note'])).not.toContain('reasoner');
  });
});

describe('heuristique du nombre de couches', () => {
  it.each([
    [30, 30, 2],
    [5, 5, 2],
    [31, 5, 4],
    [5, 31, 4],
    [80, 80, 4],
  ])('%i composants / %i nets → %i couches', async (comps, nets, expected) => {
    seedCache({ schema: schemaOf(comps, nets) });
    // Service indisponible → le handler retombe sur SA décision de couches.
    routingMock.runRealRouting.mockRejectedValue(
      new routingMock.RoutingServiceUnavailableError('down'),
    );

    const result = await handleRouting(PROJECT);

    expect(result['layers']).toBe(expected);
  });
});

describe('réutilisation du board placé', () => {
  it('utilise le .kicad_pcb du cache sans régénérer via Circuit-Synth', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    await handleRouting(PROJECT);

    expect(engineMock.runPCBEngine).not.toHaveBeenCalled();
  });

  it('régénère depuis Circuit-Synth sur cache froid (routage appelé seul)', async () => {
    await handleRouting(PROJECT);

    expect(engineMock.runPCBEngine).toHaveBeenCalledTimes(1);
  });
});

describe('préparation du board avant routage', () => {
  it('retire les pistes TS pré-placement avant de router', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    await handleRouting(PROJECT);

    const sent = routingMock.runRealRouting.mock.calls[0]?.[0] as { kicadPcbContent: string };
    expect(PCB_WITH_TRACK).toContain('(segment');
    expect(sent.kicadPcbContent).not.toContain('(segment');
  });

  it('ajoute un plan de masse GND sur B.Cu au board routé', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    const result = await handleRouting(PROJECT);

    expect(String(result['kicad_pcb_content'])).toContain('(layer "B.Cu")');
    expect(String(result['kicad_pcb_content'])).toContain('"GND"');
  });

  it('persiste le board routé en cache pour le DRC et l’export', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    const result = await handleRouting(PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe(result['kicad_pcb_content']);
  });
});

describe('modes dégradés', () => {
  /**
   * CARACTÉRISATION — comportement actuel, pas un jugement de valeur.
   * Les deux chemins de repli renvoient routed_percent: 100 alors qu'AUCUN
   * routage n'a eu lieu (seul un plan de masse est ajouté). Conséquence :
   * shouldRescueRouting et shouldRetryPlacement sont tous deux court-circuités.
   * Ces tests verrouillent le comportement observé ; ils échoueront volontairement
   * si le repli passe un jour à un pourcentage honnête — ce qui sera un
   * changement voulu, à valider explicitement.
   */
  it('service skipped → 100% simulé, engine fallback-ts, warning remonté', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockResolvedValue(
      serviceResult({ skipped: true, warning: 'freerouting absent' }),
    );

    const result = await handleRouting(PROJECT);

    expect(result['routed_percent']).toBe(100);
    expect(result['engine']).toBe('fallback-ts');
    expect(result['warning']).toBe('freerouting absent');
  });

  it('service indisponible → 100% simulé, engine fallback-ts, warning = message d’erreur', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockRejectedValue(
      new routingMock.RoutingServiceUnavailableError('KICAD_SERVICE_URL injoignable'),
    );

    const result = await handleRouting(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['routed_percent']).toBe(100);
    expect(result['engine']).toBe('fallback-ts');
    expect(result['warning']).toBe('KICAD_SERVICE_URL injoignable');
  });

  it('erreur inattendue (non RoutingServiceUnavailableError) → même repli, boucle vivante', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockRejectedValue(new TypeError('bug inattendu'));

    const result = await handleRouting(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['engine']).toBe('fallback-ts');
    expect(result['warning']).toBe('bug inattendu');
  });

  it('schéma vide → sortie anticipée sans appeler le service de routage', async () => {
    seedCache({ schema: schemaOf(0, 0) });

    const result = await handleRouting(PROJECT);

    expect(result['routed_percent']).toBe(100);
    expect(result['engine']).toBe('fallback-ts');
    expect(routingMock.runRealRouting).not.toHaveBeenCalled();
  });
});
