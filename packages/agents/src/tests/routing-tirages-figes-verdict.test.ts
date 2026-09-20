/**
 * « Tous les tirages ont figé » = verdict sur le placement, pas panne.
 *
 * Rejeu du 2026-09-20 : carte-09/10 sortaient `skipped=true, 0 %` — la même
 * réponse qu'un service sans routeur. `handleRouting` rendait `status:'error'`
 * SANS pourcentage, et `shouldRetryPlacement` (qui lit `routed_percent`) ne se
 * déclenchait jamais : la seule chose qui aurait aidé — un autre placement —
 * n'était jamais tentée.
 *
 * Le service pose désormais `verdict: 'tirages_figes'` avec le pourcentage
 * MESURÉ sur le meilleur tirage figé. L'échec reste un échec (aucun board, cache
 * intact) ; il porte juste de quoi armer le re-tirage. Un `skipped` SANS verdict
 * reste une panne muette : `handler-routing.test.ts` le garde.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { shouldRetryPlacement, shouldRescueRouting } from '../orchestrator';

vi.mock('../engines/routing-service', () => ({
  runRealRouting: vi.fn(),
  RoutingServiceUnavailableError: class extends Error {},
}));
vi.mock('../engines/engine-router', () => ({ runPCBEngine: vi.fn() }));

import { runRealRouting } from '../engines/routing-service';
import { handleRouting } from '../tools/handlers/routing';
import { pcbStateCache } from '../tools/shared';

const PROJECT = 'p-figes';

beforeEach(() => {
  vi.mocked(runRealRouting).mockReset();
  pcbStateCache.set(PROJECT, {
    schema: { components: [{ ref: 'U1' }], nets: [] },
    kicad_pcb_content: '(kicad_pcb (footprint "X"))',
    boardW: 40, boardH: 30,
  } as never);
});

describe('verdict tirages_figes', () => {
  it('l échec porte le pourcentage mesuré et le verdict, sans board', async () => {
    vi.mocked(runRealRouting).mockResolvedValue({
      routedPercent: 17, layers: 2, skipped: true, verdict: 'tirages_figes',
      warning: 'tous les tirages ont fige',
    });
    const r = await handleRouting(PROJECT);
    expect(r['status']).toBe('error');
    expect(r['routed_percent']).toBe(17);
    expect(r['verdict']).toBe('tirages_figes');
    expect(r).not.toHaveProperty('kicad_pcb_content');
    // Cache intact : le board placé n est pas écrasé par un board non routé.
    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe('(kicad_pcb (footprint "X"))');
  });

  it('ce verdict arme le re-tirage du placement', async () => {
    vi.mocked(runRealRouting).mockResolvedValue({
      routedPercent: 0, layers: 2, skipped: true, verdict: 'tirages_figes',
    });
    const r = await handleRouting(PROJECT);
    expect(shouldRetryPlacement(r, 1)).toBe(true);
    // ⚠️ Mais PAS le reasoner : il n'y a aucun board routé à sauver, seulement
    // le board placé en cache — il l'écraserait (revue du 2026-09-20).
    expect(shouldRescueRouting(r)).toBe(false);
  });

  it('un skipped SANS verdict reste une panne muette — aucun pourcentage', async () => {
    vi.mocked(runRealRouting).mockResolvedValue({ routedPercent: 0, layers: 2, skipped: true });
    const r = await handleRouting(PROJECT);
    expect(r['status']).toBe('error');
    expect(r).not.toHaveProperty('routed_percent');
    expect(shouldRetryPlacement(r, 1)).toBe(false);
  });
});
