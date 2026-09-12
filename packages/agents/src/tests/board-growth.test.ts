import { describe, it, expect } from 'vitest';
import { nextBoardSize, MAX_GROWTHS } from '../engines/board-growth';

const s = { boardW: 125, boardH: 95, growths: 0 };

describe('nextBoardSize — D-2026-09-11-b', () => {
  it('agrandit de 20 % une carte au plafond sans 100 %', () => {
    expect(nextBoardSize(s, { routedPercent: 98, layers: 6, ceiling: 6 }))
      .toEqual({ boardW: 150, boardH: 114, growths: 1 });
  });
  it('agrandit une carte à 100 % refusée par le DRC', () => {
    expect(nextBoardSize(s, { routedPercent: 100, drcClean: false, layers: 2, ceiling: 2 }).growths).toBe(1);
  });
  it('ne change rien à 100 % / DRC propre', () => {
    expect(nextBoardSize(s, { routedPercent: 100, drcClean: true, layers: 2, ceiling: 2 })).toBe(s);
  });
  it('sous le plafond, l escalade garde la main', () => {
    expect(nextBoardSize(s, { routedPercent: 96, layers: 4, ceiling: 8 })).toBe(s);
  });
  it('au plus deux agrandissements', () => {
    expect(nextBoardSize({ ...s, growths: MAX_GROWTHS }, { routedPercent: 97, layers: 6, ceiling: 6 }).growths).toBe(MAX_GROWTHS);
  });
  it('un zéro est une panne, pas un verdict : rien n est agrandi', () => {
    expect(nextBoardSize(s, { routedPercent: 0, layers: 2, ceiling: 2 })).toBe(s);
  });
});

import { growBoardIfStalled, placementInputFor, initialGrowth } from '../orchestrator';
import { pcbStateCache } from '../tools/shared';

describe('growBoardIfStalled — câblage dans l orchestrateur', () => {
  const schema = { components: [], nets: [], connections: [] } as never;
  it('écrit la taille agrandie dans le cache et la passe au placement (plan free, plafond 2)', () => {
    pcbStateCache.set('p-croissance', { schema, boardW: 100, boardH: 60 });
    const g0 = initialGrowth('p-croissance');
    const g1 = growBoardIfStalled('p-croissance', g0, { routed_percent: 96, layers: 2 });
    expect(g1).toEqual({ boardW: 120, boardH: 72, growths: 1 });
    expect(pcbStateCache.get('p-croissance')?.boardW).toBe(120);
    expect(placementInputFor(g1)).toEqual({ board_width_mm: 120, board_height_mm: 72 });
  });
  it('sans routage connu et DRC propre, rien ne bouge', () => {
    pcbStateCache.set('p-stable', { schema, boardW: 100, boardH: 60 });
    const g0 = initialGrowth('p-stable');
    expect(growBoardIfStalled('p-stable', g0, undefined, { drc_clean: true })).toBe(g0);
    expect(placementInputFor(g0)).toEqual({});
  });
});
