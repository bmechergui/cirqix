import { describe, it, expect } from 'vitest';
import {
  routingSearchBudgetS,
  ROUTING_SEARCH_BUDGET_S,
  routingAbortMs,
  WATCHDOG_MARGIN_S,
} from '../engines/routing-budget';

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

/**
 * L'échéance du CLIENT doit couvrir le budget qu'il DEMANDE.
 *
 * Le 2026-08-20, `routingSearchBudgetS(4)` demandait 1800 s au service pendant
 * que `AbortSignal.timeout(ROUTING_TIMEOUT_MS)` raccrochait à **330 s**. Le
 * client réclamait donc 30 minutes de routage puis coupait la communication au
 * bout de 5 min 30 : tout routage dépassant 330 s échouait en
 * « service indisponible », le service continuant à travailler dans le vide.
 *
 * Même faute que les cinq autres frontières, commise dans le fichier corrigé le
 * matin même : le budget DEMANDÉ avait été relevé, l'échéance du client non.
 */
describe('échéance du client', () => {
  it('couvre toujours le budget demandé, plus la marge du garde-fou', () => {
    for (const layers of [2, 4, 8]) {
      const budgetS = routingSearchBudgetS(layers);
      expect(routingAbortMs(layers)).toBeGreaterThanOrEqual(
        (budgetS + WATCHDOG_MARGIN_S) * 1000,
      );
    }
  });

  it('ne raccroche jamais avant le service', () => {
    // La faute exacte du 2026-08-20 : 330 s d'échéance pour 1800 s demandées.
    expect(routingAbortMs(4)).toBeGreaterThan(1800_000);
  });
});

/**
 * Le moteur annoncé doit être celui qui a réellement routé.
 *
 * `handlers/routing.ts` écrivait `engine: 'kicad-tools'` EN DUR et composait sa
 * note avec — « Routage kicad-tools 91% … ». Or la cascade a quatre niveaux :
 * sur un board dense, kicad-tools rend 91 %, sous le seuil, et c'est
 * **Freerouting** qui produit le board livré.
 *
 * Mesures du 2026-08-21 sur le board STM32, qui rendent l'attribution décisive :
 * Freerouting ×3 → 0 connexion manquante en 4-5 s ; kicad-tools ×2 → 7
 * manquantes en 568-750 s. Attribuer le premier résultat au second effacerait
 * exactement ce qu'il faut voir.
 */
describe('attribution du moteur de routage', () => {
  it('lit le moteur renvoyé par le service', async () => {
    const { readRoutingEngine } = await import('../engines/routing-service.js');
    expect(readRoutingEngine({ engine: 'freerouting-api' })).toBe('freerouting-api');
    expect(readRoutingEngine({ engine: 'kicad-tools' })).toBe('kicad-tools');
  });

  it('n invente aucun moteur quand le service n en nomme pas', async () => {
    // Un service plus ancien ne renvoie pas le champ : mieux vaut ne rien dire
    // que de désigner le mauvais.
    const { readRoutingEngine } = await import('../engines/routing-service.js');
    expect(readRoutingEngine({})).toBeUndefined();
    expect(readRoutingEngine({ engine: 42 })).toBeUndefined();
  });
});
