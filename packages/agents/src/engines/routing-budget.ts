/**
 * Temps de recherche accordé au routeur, par appel.
 *
 * ⚠️ Ce n'est PAS une limite de patience, c'est une RESSOURCE. `kct route` rend
 * la main dès 100 % atteint et conserve ce qu'il a routé quand son échéance
 * tombe. Un budget large ne coûte donc rien sur un board simple, et change le
 * résultat sur un board dense.
 *
 * Défaut corrigé le 2026-08-19. Le client calculait :
 *
 *     Math.min(60 + layers * 30, ROUTING_TIMEOUT_MS / 1000)
 *
 * soit **180 s sur 4 couches**. Or la courbe mesurée (STM32 LQFP-48) donne
 * 60 s → 9 %, 300 s → 36 %, 600 s → 55 %. Le vrai plafond de production n'était
 * donc ni les 600 s du service Python, ni les 300 s de l'invocation web : c'était
 * cette heuristique, cinq fois plus serrée que tout le reste. La comparaison A/B
 * du 2026-08-19 a atteint 91 % avec 900 s ; le même board en production recevait
 * 180 s.
 *
 * Le plafond reste borné : un budget infini rendrait un routeur figé
 * irrécupérable. L'arrêt anticipé est une DÉCISION de l'utilisateur
 * (annulation), pas une constante écrite d'avance.
 */

/** Plafond par appel. Aligné sur `_ROUTE_TIMEOUT_S` du service Python. */
export const ROUTING_SEARCH_BUDGET_S = 3600;

/**
 * Budget pour un board de `layers` couches.
 *
 * Plus de couches signifie une escalade plus longue, jamais plus rapide : le
 * budget croît avec les couches, sans jamais dépasser le plafond.
 */
export function routingSearchBudgetS(layers: number): number {
  const perLayer = 600 + Math.max(0, layers) * 300;
  return Math.min(perLayer, ROUTING_SEARCH_BUDGET_S);
}
