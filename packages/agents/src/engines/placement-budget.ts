/**
 * Budget accordé au placement, par appel.
 *
 * `/place/auto` enchaîne Architecte (GA hybrid + clustering), Géomètre (CMA-ES
 * en sous-processus) et Inspecteur. Mesures :
 *   -  34-45 s — board NE555, 8 composants (`examples/led-blinker-full-pipeline`)
 *   - 175 s    — board STM32 de `examples/stm32-validation`
 *   - > 215 s  — board STM32 de 21 composants produit par la chaîne le 2026-08-20
 *
 * Ce dernier cas a expiré DEUX FOIS contre l'ancienne constante de 180 s : le
 * run entier s'est terminé sans qu'aucun composant soit placé, donc sans jamais
 * atteindre le routage. Aucun `POST /place/auto` n'apparaît dans le journal du
 * service — le client abandonnait avant que le placement rende sa réponse.
 *
 * ⚠️ Même classe de défaut que le budget de routage corrigé le 2026-08-19 : une
 * constante CLIENT plus serrée que le travail qu'elle enserre. Tant que la route
 * web plafonnait à 300 s, ces constantes restaient masquées par un plafond plus
 * bas qu'elles. Le worker ayant retiré ce plafond, elles deviennent LE plafond.
 *
 * Le budget reste borné : l'arrêt anticipé légitime est une DÉCISION de
 * l'utilisateur (annulation), mais un budget infini rendrait un placement figé
 * impossible à abandonner.
 *
 * Garde : tests/placement-budget.test.ts.
 */
export const PLACEMENT_TIMEOUT_MS = 900_000;
