import { describe, it, expect } from 'vitest';
import { PLAN_ENTITLEMENTS, maxLayersForPlan } from '@cirqix/types';

/**
 * Droits attachés au plan (Phase 5).
 *
 * Le plan était fiable depuis la PR #125 — le webhook le remet enfin à `free`
 * en fin d'abonnement — mais il ne gouvernait rien. Les couches étaient
 * décidées par une heuristique sur le nombre de composants, sans plafond : un
 * compte gratuit obtenait des boards 4 couches, sensiblement plus chers à
 * fabriquer.
 *
 * Ce module est la source de vérité unique. Dupliquer la table ailleurs
 * garantirait qu'un futur changement de grille tarifaire n'en corrige qu'une
 * copie.
 */

describe('PLAN_ENTITLEMENTS', () => {
  it('couvre tous les plans existants', () => {
    // Un plan absent de la table donnerait `undefined` et, sans garde, un
    // plafond `undefined` qui ne plafonne rien.
    expect(Object.keys(PLAN_ENTITLEMENTS).sort()).toEqual([
      'enterprise',
      'free',
      'pro',
      'pro_max',
    ]);
  });

  it('applique la grille annoncée dans CLAUDE.md', () => {
    expect(PLAN_ENTITLEMENTS.free.maxLayers).toBe(2);
    expect(PLAN_ENTITLEMENTS.pro.maxLayers).toBe(4);
    expect(PLAN_ENTITLEMENTS.pro_max.maxLayers).toBe(8);
    expect(PLAN_ENTITLEMENTS.enterprise.maxLayers).toBe(8);
  });

  it("n'ouvre la simulation qu'aux plans payants", () => {
    expect(PLAN_ENTITLEMENTS.free.canSimulate).toBe(false);
    expect(PLAN_ENTITLEMENTS.pro.canSimulate).toBe(true);
    expect(PLAN_ENTITLEMENTS.pro_max.canSimulate).toBe(true);
    expect(PLAN_ENTITLEMENTS.enterprise.canSimulate).toBe(true);
  });

  it('ne propose jamais un nombre de couches non fabricable', () => {
    // Le service KiCad refuse tout ce qui n'est pas 2, 4 ou 8
    // (RouteAutoRequest.layers). Une valeur hors de ce jeu ferait échouer le
    // routage au lieu de le restreindre.
    for (const e of Object.values(PLAN_ENTITLEMENTS)) {
      expect([2, 4, 8]).toContain(e.maxLayers);
    }
  });
});

describe('maxLayersForPlan', () => {
  it('retourne le plafond du plan', () => {
    expect(maxLayersForPlan('pro')).toBe(4);
  });

  it('retombe sur le plan le plus restrictif quand le plan est inconnu', () => {
    // Un plan absent, nul, ou une valeur inattendue venue de la base ne doit
    // JAMAIS ouvrir de droits. Le défaut sûr est le plan gratuit : un
    // utilisateur lésé le signale, un droit accordé à tort reste invisible.
    expect(maxLayersForPlan(undefined)).toBe(2);
    expect(maxLayersForPlan(null)).toBe(2);
    expect(maxLayersForPlan('platinum' as never)).toBe(2);
    expect(maxLayersForPlan('' as never)).toBe(2);
  });
});
