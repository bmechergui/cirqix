import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleErc — porte de sortie du schéma. Un schéma non validé produit un PCB
 * non routable ; le prompt orchestrateur interdit d'ailleurs de sauter cette étape.
 *
 * Particularité par rapport aux autres handlers dégradés : il existe ici un
 * vérificateur de repli RÉEL (`runErcFallback`, ERC TypeScript pur — refs
 * dupliquées, nets flottants, GND manquant, composants non connectés). Quand
 * kicad-cli est indisponible, la bonne réponse n'est donc pas d'échouer mais de
 * faire tourner ce contrôle et d'en honorer le verdict. `runErcFallback` n'est
 * PAS mocké ici : c'est du code pur, son intégration fait partie du contrat.
 *
 * Invariant : ERC_CLEAN ne peut être émis que par un contrôle réellement
 * exécuté et réellement passé — jamais parce qu'aucun contrôle n'a eu lieu.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const ercMock = vi.hoisted(() => {
  class ErcServiceUnavailableError extends Error {}
  return { runRealErc: vi.fn(), ErcServiceUnavailableError };
});
vi.mock('../engines/erc-service', () => ercMock);

import { handleErc } from '../tools/handlers/erc';
import { pcbStateCache } from '../tools/shared';

const SCH = '(kicad_sch (version 20231120))';
const FIXED_SCH = '(kicad_sch (version 20231120) (fixed yes))';
const PROJECT = 'p1';

/** Passe l'ERC TypeScript : refs uniques, nets à 2 pins, GND présent, tout connecté. */
const CLEAN_SCHEMA = {
  components: [
    { ref: 'R1', value: '1k' },
    { ref: 'D1', value: 'LED' },
  ],
  nets: [],
  connections: [
    { name: 'GND', pins: [{ ref: 'R1', pin: '1' }, { ref: 'D1', pin: '2' }] },
    { name: 'VCC', pins: [{ ref: 'R1', pin: '2' }, { ref: 'D1', pin: '1' }] },
  ],
};

/** Échoue l'ERC TypeScript : pas de net GND → erreur bloquante. */
const DIRTY_SCHEMA = {
  components: [{ ref: 'R1', value: '1k' }],
  nets: [],
  connections: [{ name: 'VCC', pins: [{ ref: 'R1', pin: '1' }, { ref: 'R1', pin: '2' }] }],
};

function ercResult(overrides: Record<string, unknown> = {}) {
  return {
    ercClean: true,
    violations: [],
    fixedCount: 0,
    skipped: false,
    kicadSchContent: FIXED_SCH,
    ...overrides,
  };
}

beforeEach(() => {
  pcbStateCache.clear();
  ercMock.runRealErc.mockReset();
  ercMock.runRealErc.mockResolvedValue(ercResult());
});

function seedCache(overrides: Record<string, unknown> = {}) {
  pcbStateCache.set(PROJECT, {
    schema: CLEAN_SCHEMA,
    boardW: 50,
    boardH: 40,
    kicad_sch_content: SCH,
    ...overrides,
  } as never);
}

describe('ERC kicad-cli nominal', () => {
  it('promeut ERC_CLEAN quand le service confirme 0 violation', async () => {
    seedCache();

    const result = await handleErc({}, PROJECT);

    expect(result['pcb_status']).toBe('ERC_CLEAN');
    expect(result['engine']).toBe('kicad-cli');
  });

  it('reste en SCHEMA_DONE tant qu’il reste des violations', async () => {
    seedCache();
    ercMock.runRealErc.mockResolvedValue(
      ercResult({ ercClean: false, violations: [{ severity: 'error', message: 'x' }] }),
    );

    const result = await handleErc({}, PROJECT);

    expect(result['pcb_status']).toBe('SCHEMA_DONE');
  });

  it('persiste le schéma auto-corrigé en cache', async () => {
    seedCache();
    ercMock.runRealErc.mockResolvedValue(ercResult({ fixedCount: 2 }));

    await handleErc({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_sch_content).toBe(FIXED_SCH);
  });

  it.each([
    [{}, true],
    [{ auto_fix: false }, false],
  ])('transmet auto_fix (%o)', async (input, expected) => {
    seedCache();

    await handleErc(input, PROJECT);

    expect(ercMock.runRealErc.mock.calls[0]?.[0]).toMatchObject({ autoFix: expected });
  });
});

describe('repli sur l’ERC TypeScript — un vrai contrôle, pas un laissez-passer', () => {
  it.each([
    [
      'service ayant sauté l’ERC',
      () => ercMock.runRealErc.mockResolvedValue(ercResult({ skipped: true, ercClean: false })),
    ],
    [
      'service injoignable',
      () =>
        ercMock.runRealErc.mockRejectedValue(
          new ercMock.ErcServiceUnavailableError('KICAD_SERVICE_URL not configured'),
        ),
    ],
  ])('%s + schéma sain → ERC_CLEAN accordé par l’ERC TypeScript', async (_label, arrange) => {
    seedCache({ schema: CLEAN_SCHEMA });
    arrange();

    const result = await handleErc({}, PROJECT);

    expect(result['pcb_status']).toBe('ERC_CLEAN');
    expect(result['engine']).toBe('ts-erc');
  });

  it.each([
    [
      'service ayant sauté l’ERC',
      () => ercMock.runRealErc.mockResolvedValue(ercResult({ skipped: true, ercClean: false })),
    ],
    [
      'service injoignable',
      () => ercMock.runRealErc.mockRejectedValue(new Error('down')),
    ],
  ])('%s + schéma fautif → SCHEMA_DONE, le défaut est remonté', async (_label, arrange) => {
    seedCache({ schema: DIRTY_SCHEMA });
    arrange();

    const result = await handleErc({}, PROJECT);

    expect(result['pcb_status']).toBe('SCHEMA_DONE');
    expect(result['engine']).toBe('ts-erc');
    expect(Array.isArray(result['ercViolations'])).toBe(true);
    expect((result['ercViolations'] as unknown[]).length).toBeGreaterThan(0);
  });
});

describe('jamais ERC_CLEAN sans contrôle exécuté', () => {
  it('aucun .kicad_sch en cache → erreur, pas un schéma absent déclaré propre', async () => {
    const result = await handleErc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('ERC_CLEAN');
    expect(ercMock.runRealErc).not.toHaveBeenCalled();
  });

  it('service injoignable ET aucun schéma à contrôler → erreur', async () => {
    // Un .kicad_sch existe, mais pas le schéma JSON que l'ERC TypeScript exige :
    // aucun des deux contrôleurs ne peut statuer.
    seedCache({ schema: { components: [], nets: [] } });
    ercMock.runRealErc.mockRejectedValue(new Error('down'));

    const result = await handleErc({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('ERC_CLEAN');
  });
});
