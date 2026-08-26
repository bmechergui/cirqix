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
import { pcbStateCache, setProjectPlan, clearProjectPlan } from '../tools/shared';

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
    // Le service NOMME son moteur depuis le 2026-08-21 : la cascade a quatre
    // niveaux et le handler n'a plus le droit de le deviner.
    engine: 'kicad-tools',
    ...overrides,
  };
}

const PROJECT = 'p1';

beforeEach(() => {
  pcbStateCache.clear();
  clearProjectPlan(PROJECT);
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

describe('couches annoncées', () => {
  /**
   * Deux choses distinctes portent le même nom :
   *   - les couches DEMANDÉES — une décision de l'agent, bornée par le plan,
   *     d'où le type `2 | 4 | 8` de `DesignJson.layers` ;
   *   - les couches MESURÉES sur le board livré, que le service compte depuis
   *     le 2026-08-21 dans le bloc `(layers …)` du fichier.
   *
   * Le handler forçait la seconde dans le type de la première
   * (`service.layers as 2 | 4 | 8`). Un board à 6 couches serait passé pour un
   * 2, 4 ou 8 — un chiffre faux, présenté comme une mesure.
   */
  it('remonte le nombre de couches mesuré, même hors des valeurs de plan', async () => {
    seedCache();
    routingMock.runRealRouting.mockResolvedValue(serviceResult({ layers: 6 }));

    const result = await handleRouting(PROJECT);

    expect(result['layers']).toBe(6);
  });
});

describe('propagation du routed_percent réel', () => {
  it.each([0, 43, 73, 91, 99, 100])(
    'remonte %i%% tel quel — jamais un 100 arbitraire',
    async (pct) => {
      seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
      routingMock.runRealRouting.mockResolvedValue(serviceResult({ routedPercent: pct }));

      const result = await handleRouting(PROJECT);

      expect(result['routed_percent']).toBe(pct);
      // Le moteur est PROPAGE, jamais devine.
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

describe('plafond de couches demandé au service', () => {
  it.each([
    [30, 30],
    [5, 5],
    [31, 5],
    [80, 80],
  ])('%i composants / %i nets → le plafond du plan, quelle que soit la taille',
    async (comps, nets) => {
    // ⚠️ Ce bloc mesurait auparavant une HEURISTIQUE — « ≤ 30 composants et
    // ≤ 30 nets → 2 couches, sinon 4 ». Elle a été retirée le 2026-08-26.
    //
    // Elle était une ESTIMATION faite AVANT le routage, et elle privait le
    // service d'escalader sur une MESURE : `_layer_ladder(2)` ne rend qu'un
    // seul palier, donc monter à 4 était structurellement impossible. Mesuré
    // sur l'ESP32 du banc — 20 composants, 5 nets, bloqué à 2 couches,
    // 25 % routé, 8 connexions manquantes.
    //
    // Le handler envoie désormais le PLAFOND du plan. Le service part toujours
    // de 2 et s'arrête au premier palier qui route à 100 %, donc une petite
    // carte reste en 2 couches — la garantie tient par construction, chez lui.
    seedCache({ schema: schemaOf(comps, nets), kicad_pcb_content: PCB_WITH_TRACK });
    setProjectPlan(PROJECT, 'pro');

    await handleRouting(PROJECT);

    const sent = routingMock.runRealRouting.mock.calls[0]?.[0] as { layers: number };
    expect(sent.layers).toBe(4);
  });

  it('un compte gratuit reste plafonné à 2, même sur un gros schéma', async () => {
    // Le gate commercial est intact : c'est la seule borne qu'on conserve.
    seedCache({ schema: schemaOf(80, 80), kicad_pcb_content: PCB_WITH_TRACK });
    setProjectPlan(PROJECT, 'free');

    await handleRouting(PROJECT);

    const sent = routingMock.runRealRouting.mock.calls[0]?.[0] as { layers: number };
    expect(sent.layers).toBe(2);
  });
});

describe('réutilisation du board placé', () => {
  it('utilise le .kicad_pcb du cache sans régénérer via Circuit-Synth', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });

    await handleRouting(PROJECT);

    expect(engineMock.runPCBEngine).not.toHaveBeenCalled();
  });

  it('régénère depuis Circuit-Synth sur cache froid (routage appelé seul)', async () => {
    // Schéma présent, board absent — le handler doit régénérer via Circuit-Synth.
    // Sans schéma, fail-closed (schéma vide) avant toute régénération.
    seedCache(); // pas de kicad_pcb_content

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

describe('fail fast quand aucun routage n’a eu lieu', () => {
  /**
   * Un board sans piste n'est pas livrable. Les deux chemins dégradés
   * renvoyaient auparavant routed_percent: 100 avec un simple plan de masse —
   * ce qui désarmait shouldRescueRouting ET shouldRetryPlacement, et faisait
   * enchaîner Sonnet sur DRC/export en annonçant « routé à 100% ».
   *
   * Ils remontent désormais une erreur, par cohérence avec handlePlacement.
   * L'invariant clé : AUCUN routed_percent n'est émis sur ces chemins, donc
   * aucun trigger déterministe ne peut être armé par un pourcentage fantôme.
   */
  it.each([
    [
      'service skipped',
      () =>
        routingMock.runRealRouting.mockResolvedValue(
          serviceResult({ skipped: true, warning: 'freerouting absent' }),
        ),
      'freerouting absent',
    ],
    [
      'service injoignable',
      () =>
        routingMock.runRealRouting.mockRejectedValue(
          new routingMock.RoutingServiceUnavailableError('KICAD_SERVICE_URL injoignable'),
        ),
      'KICAD_SERVICE_URL injoignable',
    ],
    [
      'erreur inattendue',
      () => routingMock.runRealRouting.mockRejectedValue(new TypeError('bug inattendu')),
      'bug inattendu',
    ],
  ])('%s → status error portant la cause', async (_label, arrange, expectedCause) => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    arrange();

    const result = await handleRouting(PROJECT);

    expect(result['status']).toBe('error');
    expect(result['error']).toBe(expectedCause);
  });

  it('n’émet AUCUN routed_percent — aucun trigger armé par un pourcentage fantôme', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockRejectedValue(new Error('down'));

    const result = await handleRouting(PROJECT);

    expect(result).not.toHaveProperty('routed_percent');
    expect(result).not.toHaveProperty('pcb_status');
  });

  it('ne corrompt pas le cache avec un board non routé', async () => {
    seedCache({ kicad_pcb_content: 'BOARD_PLACE' });
    routingMock.runRealRouting.mockRejectedValue(new Error('down'));

    await handleRouting(PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe('BOARD_PLACE');
  });

  it('mentionne KICAD_SERVICE_URL pour orienter le diagnostic', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockRejectedValue(new Error('down'));

    const result = await handleRouting(PROJECT);

    expect(String(result['note'])).toContain('KICAD_SERVICE_URL');
  });

  it('schéma vide → erreur, pas un 100% fantôme qui désarme le sauvetage', async () => {
    seedCache({ schema: schemaOf(0, 0) });

    const result = await handleRouting(PROJECT);

    expect(result['status']).toBe('error');
    expect(result).not.toHaveProperty('routed_percent');
    expect(result).not.toHaveProperty('via_count');
    expect(result).not.toHaveProperty('track_length_mm');
    expect(String(result['error'])).toMatch(/schéma vide/i);
    expect(routingMock.runRealRouting).not.toHaveBeenCalled();
  });
});

describe('métriques absentes — omettre plutôt que fabriquer', () => {
  /**
   * via_count / track_length_mm retombaient sur comps*0.5 et nets*15 quand le
   * service ne les renvoyait pas. Une heuristique se lit comme une mesure réelle
   * et fausse le diagnostic. Omettre le champ est le contrat correct.
   */
  it('omet via_count et track_length_mm si le service ne les fournit pas', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    const bare = serviceResult();
    delete (bare as { viaCount?: number }).viaCount;
    delete (bare as { trackLengthMm?: number }).trackLengthMm;
    routingMock.runRealRouting.mockResolvedValue(bare);

    const result = await handleRouting(PROJECT);

    expect(result['status']).toBe('success');
    expect(result).not.toHaveProperty('via_count');
    expect(result).not.toHaveProperty('track_length_mm');
  });

  it('propage les métriques réelles du service quand elles sont présentes', async () => {
    seedCache({ kicad_pcb_content: PCB_WITH_TRACK });
    routingMock.runRealRouting.mockResolvedValue(
      serviceResult({ viaCount: 7, trackLengthMm: 88.5 }),
    );

    const result = await handleRouting(PROJECT);

    expect(result['via_count']).toBe(7);
    expect(result['track_length_mm']).toBe(88.5);
  });
});
