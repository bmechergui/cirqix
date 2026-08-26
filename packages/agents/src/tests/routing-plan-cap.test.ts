import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Le plafond de couches du plan est-il RÉELLEMENT appliqué au routage ?
 *
 * `handleRouting` choisissait ses couches par une heuristique sur la taille du
 * schéma — 2 en deçà de 30 composants/nets, 4 au-delà — sans jamais consulter
 * le plan. Un compte gratuit obtenait donc des boards 4 couches.
 *
 * Ces tests portent sur ce que le handler DEMANDE au service KiCad, seul
 * endroit où le plafond a un effet : le gater côté client serait cosmétique.
 */

const runRealRoutingMock = vi.hoisted(() => vi.fn());
vi.mock('../engines/routing-service', () => ({
  runRealRouting: runRealRoutingMock,
  RoutingServiceUnavailableError: class extends Error {},
}));

import { handleRouting } from '../tools/handlers/routing';
import { pcbStateCache, setProjectPlan, clearProjectPlan } from '../tools/shared';

const PROJECT = 'p-cap';

/** Un schéma volumineux : l'heuristique seule réclamerait 4 couches. */
function seedLargeSchema(plan?: string) {
  const many = (n: number, p: string) =>
    Array.from({ length: n }, (_, i) => ({ ref: `${p}${i}`, footprint: 'X' }));
  pcbStateCache.set(PROJECT, {
    schema: {
      components: many(40, 'U') as never,
      nets: many(40, 'N') as never,
    } as never,
    boardW: 80,
    boardH: 60,
    kicad_pcb_content: '(kicad_pcb)',
  } as never);
  if (plan) setProjectPlan(PROJECT, plan as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.clear();
  clearProjectPlan(PROJECT);
  runRealRoutingMock.mockResolvedValue({
    skipped: false,
    routedPercent: 100,
    layers: 2,
    kicadPcbContent: '(kicad_pcb routed)',
  });
});

function demandedLayers(): number {
  return (runRealRoutingMock.mock.calls[0]?.[0] as { layers: number }).layers;
}

describe('handleRouting — plafond de couches par plan', () => {
  it('plafonne un compte gratuit à 2 couches malgré un gros schéma', async () => {
    seedLargeSchema('free');

    await handleRouting(PROJECT);

    expect(demandedLayers()).toBe(2);
  });

  it('laisse un compte Pro monter à 4', async () => {
    seedLargeSchema('pro');

    await handleRouting(PROJECT);

    expect(demandedLayers()).toBe(4);
  });

  it("envoie le PLAFOND, et le board livré ne le suit pas aveuglément", async () => {
    // ⚠️ Cette garantie a changé d'endroit le 2026-08-26, et il faut savoir
    // pourquoi. Le test exigeait auparavant que la valeur ENVOYÉE reste à 2
    // pour un petit schéma, au motif que « le plafond restreint, il ne
    // prescrit pas ».
    //
    // La crainte est juste, l'instrument était faux. `layers` est un PLAFOND
    // côté service : `_layer_ladder(8)` rend [2, 4, 6, 8] et l'escalade
    // s'arrête au premier palier qui route à 100 %. Envoyer 8 ne fabrique
    // donc pas 8 — le service part toujours de 2.
    //
    // En revanche, envoyer une ESTIMATION rendait l'escalade impossible :
    // `_layer_ladder(2)` ne contient qu'un barreau. Mesuré sur l'ESP32 du
    // banc — 20 composants, 5 nets, bloqué à 2 couches, 25 % routé,
    // 8 connexions manquantes, alors que 4 couches l'auraient sauvé.
    //
    // La garantie « pas plus de couches que nécessaire » appartient donc au
    // SERVICE, qui la tient par construction, et se vérifie sur le board
    // LIVRÉ — pas sur la requête.
    pcbStateCache.set(PROJECT, {
      schema: { components: [{ ref: 'R1' }], nets: [{ name: 'N1' }] } as never,
      boardW: 50,
      boardH: 50,
      kicad_pcb_content: '(kicad_pcb)',
    } as never);
    setProjectPlan(PROJECT, 'pro_max');

    await handleRouting(PROJECT);

    expect(demandedLayers()).toBe(8);
  });

  it('survit à une réécriture complète du cache de board', async () => {
    // Le piège évité en concevant ceci : neuf handlers écrivent dans
    // `pcbStateCache`, et plusieurs — `handleSchema` en tête, donc dès la
    // PREMIÈRE étape — réécrivent l'entrée EN ENTIER au lieu de l'étendre.
    // Un plan rangé là serait effacé en silence, chaque compte retomberait sur
    // `free`, et les abonnés payants seraient plafonnés à 2 couches sans
    // qu'aucun test de handler ne le voie.
    setProjectPlan(PROJECT, 'pro');
    seedLargeSchema(); // simule la réécriture wholesale d'un handler amont

    await handleRouting(PROJECT);

    expect(demandedLayers()).toBe(4);
  });

  it('retombe sur le plan le plus restrictif quand le plan est absent du cache', async () => {
    // Un pipeline qui n'a pas semé le plan ne doit pas ouvrir les 4 couches
    // par omission — le défaut sûr est le plan gratuit.
    seedLargeSchema(undefined);

    await handleRouting(PROJECT);

    expect(demandedLayers()).toBe(2);
  });
});
