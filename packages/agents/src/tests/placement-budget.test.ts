import { describe, it, expect } from 'vitest';
import { PLACEMENT_TIMEOUT_MS } from '../engines/placement-budget';
import { ROUTING_SEARCH_BUDGET_S } from '../engines/routing-budget';

/**
 * Budget accordé au placement, côté client.
 *
 * Même classe de défaut que le budget de routage corrigé le 2026-08-19 : une
 * constante côté client plus serrée que le travail qu'elle enserre. Tant que la
 * route web plafonnait à 300 s, ces constantes étaient masquées par un plafond
 * plus bas qu'elles. Le worker ayant retiré ce plafond, elles deviennent LE
 * plafond — et doivent donc être mesurées, pas devinées.
 */

describe('budget de placement', () => {
  it('dépasse le placement le plus long mesuré', () => {
    // Mesures : 34-45 s sur le board NE555 (8 composants) ; 175 s sur le board
    // STM32 de `examples/stm32-validation` ; > 215 s sur un STM32 de 21
    // composants généré par la chaîne le 2026-08-20 — ce dernier a expiré DEUX
    // FOIS à 180 s, faisant échouer tout le run avant même le routage.
    expect(PLACEMENT_TIMEOUT_MS).toBeGreaterThan(215_000);
  });

  it('reste borné — un service figé doit rester récupérable', () => {
    // L'arrêt anticipé légitime est une DÉCISION de l'utilisateur (annulation),
    // pas une constante ; mais un budget infini rendrait un placement bloqué
    // impossible à abandonner.
    expect(PLACEMENT_TIMEOUT_MS).toBeLessThanOrEqual(ROUTING_SEARCH_BUDGET_S * 1000);
  });
});
