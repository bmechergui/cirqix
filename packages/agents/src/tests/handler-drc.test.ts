import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleDrc — le dernier verrou avant fabrication.
 *
 * `pcb_status: 'DRC_CLEAN'` n'est pas qu'un libellé d'UI : orchestrator-bridge le
 * persiste dans projects.status, et POST /api/jlcpcb/order refuse toute commande
 * dont le statut n'est pas DRC_CLEAN. Déclarer DRC_CLEAN un board dont le DRC n'a
 * PAS tourné ouvre donc la commande JLCPCB — de l'argent et du matériel réels —
 * sur une carte jamais vérifiée.
 *
 * Invariant central de ce fichier : DRC_CLEAN ne peut être émis QUE par un DRC
 * réellement exécuté et réellement propre.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const drcMock = vi.hoisted(() => {
  class DrcServiceUnavailableError extends Error {}
  return { runRealDrc: vi.fn(), DrcServiceUnavailableError };
});
vi.mock('../engines/drc-service', () => drcMock);

import { handleDrc } from '../tools/handlers/drc';
import { pcbStateCache } from '../tools/shared';

const PCB = '(kicad_pcb (net 1 "GND"))';
const FIXED_PCB = '(kicad_pcb (net 1 "GND") (fixed yes))';
const PROJECT = 'p1';

function drcResult(overrides: Record<string, unknown> = {}) {
  return {
    drcClean: true,
    violations: [],
    fixedCount: 0,
    skipped: false,
    kicadPcbContent: FIXED_PCB,
    ...overrides,
  };
}

beforeEach(() => {
  pcbStateCache.clear();
  drcMock.runRealDrc.mockReset();
  drcMock.runRealDrc.mockResolvedValue(drcResult());
});

function seedCache(overrides: Record<string, unknown> = {}) {
  pcbStateCache.set(PROJECT, {
    schema: { components: [{ ref: 'R1' }], nets: [{ name: 'GND' }] },
    boardW: 50,
    boardH: 40,
    kicad_pcb_content: PCB,
    ...overrides,
  } as never);
}

describe('DRC réellement exécuté et propre', () => {
  it('promeut DRC_CLEAN quand le service confirme 0 violation', async () => {
    seedCache();

    const result = await handleDrc({}, PROJECT);

    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('DRC_CLEAN');
    expect(result['drc_clean']).toBe(true);
  });

  it('reste en ROUTING_DONE tant qu’il reste des violations', async () => {
    seedCache();
    drcMock.runRealDrc.mockResolvedValue(
      drcResult({ drcClean: false, violations: [{ type: 'clearance' }, { type: 'short' }] }),
    );

    const result = await handleDrc({}, PROJECT);

    expect(result['pcb_status']).toBe('ROUTING_DONE');
    expect(result['drc_clean']).toBe(false);
    expect(result['drcViolations']).toHaveLength(2);
  });

  it('persiste le board corrigé en cache pour l’export', async () => {
    seedCache();
    drcMock.runRealDrc.mockResolvedValue(drcResult({ fixedCount: 3 }));

    await handleDrc({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe(FIXED_PCB);
  });

  it('enregistre drc_clean:true en cache quand le DRC est propre', async () => {
    seedCache();

    await handleDrc({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.drc_clean).toBe(true);
  });

  it('enregistre drc_clean:false en cache quand des violations restent', async () => {
    seedCache();
    drcMock.runRealDrc.mockResolvedValue(
      drcResult({ drcClean: false, violations: [{ type: 'clearance' }] }),
    );

    await handleDrc({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.drc_clean).toBe(false);
    expect(pcbStateCache.get(PROJECT)?.drc_clean).not.toBe(true);
  });

  it('mentionne les auto-fix appliqués dans la note', async () => {
    seedCache();
    drcMock.runRealDrc.mockResolvedValue(drcResult({ fixedCount: 3 }));

    const result = await handleDrc({}, PROJECT);

    expect(String(result['note'])).toContain('3');
  });
});

describe('option auto_fix', () => {
  it('active l’auto-fix par défaut', async () => {
    seedCache();

    await handleDrc({}, PROJECT);

    expect(drcMock.runRealDrc.mock.calls[0]?.[0]).toMatchObject({ autoFix: true });
  });

  it('respecte auto_fix: false', async () => {
    seedCache();

    await handleDrc({ auto_fix: false }, PROJECT);

    expect(drcMock.runRealDrc.mock.calls[0]?.[0]).toMatchObject({ autoFix: false });
  });
});

describe('jamais DRC_CLEAN sans DRC exécuté', () => {
  /**
   * Les trois chemins ci-dessous renvoyaient auparavant pcb_status:'DRC_CLEAN'
   * + drc_clean:true SANS qu'aucun DRC n'ait tourné — ce qui débloquait
   * POST /api/jlcpcb/order sur un board non vérifié. Ils échouent désormais.
   */
  it('aucun PCB en cache → erreur, pas un board vide déclaré propre', async () => {
    const result = await handleDrc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(result['drc_clean']).not.toBe(true);
    expect(drcMock.runRealDrc).not.toHaveBeenCalled();
  });

  it('service ayant sauté le DRC (kicad-cli absent) → erreur', async () => {
    seedCache();
    drcMock.runRealDrc.mockResolvedValue(
      drcResult({ skipped: true, drcClean: false, warning: 'kicad-cli indisponible' }),
    );

    const result = await handleDrc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(String(result['error'])).toContain('kicad-cli indisponible');
  });

  it('service injoignable → erreur, jamais un DRC_CLEAN de repli', async () => {
    seedCache();
    drcMock.runRealDrc.mockRejectedValue(
      new drcMock.DrcServiceUnavailableError('KICAD_SERVICE_URL not configured'),
    );

    const result = await handleDrc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(result['error']).toBe('KICAD_SERVICE_URL not configured');
  });

  it('erreur inattendue → erreur également', async () => {
    seedCache();
    drcMock.runRealDrc.mockRejectedValue(new TypeError('bug inattendu'));

    const result = await handleDrc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
  });

  it('ne corrompt pas le cache quand le DRC échoue', async () => {
    seedCache();
    drcMock.runRealDrc.mockRejectedValue(new Error('down'));

    await handleDrc({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe(PCB);
  });

  it('mentionne KICAD_SERVICE_URL pour orienter le diagnostic', async () => {
    seedCache();
    drcMock.runRealDrc.mockRejectedValue(new Error('down'));

    const result = await handleDrc({}, PROJECT);

    expect(String(result['note'])).toContain('KICAD_SERVICE_URL');
  });
});
