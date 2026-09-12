/**
 * Agrandissement d'une carte qui stagne à son plafond de couches
 * (D-2026-09-11-b, validée). Miroir de `run_pipeline.py::taille_suivante` —
 * la règle est la même dans le banc et en production.
 *
 * Mesure carte-08 (56 composants) : 98 % à 2, 4 et 6 couches pendant 24 h ;
 * +20 % de contour → 100 % / 0 erreur à 2 couches au premier tirage. Quand
 * chaque palier rend le même pourcentage, ce n'est plus le nombre de couches
 * qui manque, c'est la place : on agrandit, au plus deux fois.
 *
 * Sous le plafond, l'escalade garde la main. Un « 0 % » n'est pas un verdict
 * de routage mais une panne (aucun moteur) : il n'agrandit rien.
 */
export const GROWTH_FACTOR = 1.2;
export const MAX_GROWTHS = 2;

export interface BoardGrowth {
  readonly boardW: number;
  readonly boardH: number;
  readonly growths: number;
}

export interface GrowthEvidence {
  readonly routedPercent: number;
  /** `false` = DRC exécuté et refusé ; `true` ou absent = rien à reprocher. */
  readonly drcClean?: boolean | undefined;
  readonly layers: number;
  readonly ceiling: number;
}

function roundMm(x: number): number {
  return Math.round(x * 10) / 10;
}

export function nextBoardSize(state: BoardGrowth, e: GrowthEvidence): BoardGrowth {
  const complete = e.routedPercent >= 100 && e.drcClean !== false;
  if (complete) return state;
  if (e.routedPercent <= 0) return state;
  if (e.layers < e.ceiling) return state;
  if (state.growths >= MAX_GROWTHS) return state;
  return {
    boardW: roundMm(state.boardW * GROWTH_FACTOR),
    boardH: roundMm(state.boardH * GROWTH_FACTOR),
    growths: state.growths + 1,
  };
}
