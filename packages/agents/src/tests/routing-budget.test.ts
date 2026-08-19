import { describe, it, expect } from 'vitest';
import { routingSearchBudgetS, ROUTING_SEARCH_BUDGET_S } from '../engines/routing-budget';

/**
 * Budget de recherche accordé au routeur, par appel.
 *
 * Défaut corrigé le 2026-08-19. Le client calculait :
 *
 *     Math.min(60 + layers * 30, ROUTING_TIMEOUT_MS / 1000)
 *
 * soit **180 s sur un board 4 couches** — alors que la courbe mesurée sur
 * STM32 LQFP-48 donne 300 s -> 36 % de complétion. Le vrai plafond de production
 * n'était donc ni les 600 s du service Python ni les 300 s de l'invocation :
 * c'était cette heuristique, cinq fois plus serrée que tout le reste.
 *
 * La comparaison A/B du 2026-08-19 a tourné à `--timeout 900` et atteint 91 %.
 * Le même board en production recevait 180 s.
 *
 * `--timeout` n'est PAS une limite de patience : `kct route` rend la main dès
 * 100 % atteint. Un budget large ne coûte donc rien sur un board simple, et
 * change tout sur un board dense.
 */
describe('budget de recherche du routeur', () => {
  it('accorde au moins 20 min — ordre de grandeur d un routage complexe', () => {
    expect(ROUTING_SEARCH_BUDGET_S).toBeGreaterThanOrEqual(1200);
  });

  it('ne rationne plus les boards multicouches', () => {
    // L'ancienne heuristique donnait 180 s à 4 couches et 300 s à 8.
    expect(routingSearchBudgetS(4)).toBeGreaterThan(180);
    expect(routingSearchBudgetS(8)).toBeGreaterThan(300);
  });

  it('accorde au moins autant de temps quand il y a plus de couches', () => {
    // Une escalade de couches ne peut pas être plus rapide à router.
    expect(routingSearchBudgetS(8)).toBeGreaterThanOrEqual(routingSearchBudgetS(2));
  });

  it('reste borné — un budget infini empêcherait toute récupération', () => {
    expect(routingSearchBudgetS(8)).toBeLessThanOrEqual(ROUTING_SEARCH_BUDGET_S);
  });
});
