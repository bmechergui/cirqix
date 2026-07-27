import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handlePlacement — résout le schéma et les dimensions du board, puis délègue au
 * service pcbnew. Deux invariants portent tout le reste :
 *
 *   - la résolution en cascade (input → cache → défaut) : un schéma résolu à vide
 *     par erreur produit un board sans composants que le routage déclarera
 *     « 100% routé » sans que rien n'ait été placé ;
 *   - le FAIL FAST en cas de service indisponible (placement-fallback.ts a été
 *     supprimé volontairement, cf. CLAUDE.md) : le handler doit renvoyer
 *     status:'error', jamais un placement inventé.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const engineMock = vi.hoisted(() => ({ runPCBEngine: vi.fn() }));
vi.mock('../engines/engine-router', () => engineMock);

const placementMock = vi.hoisted(() => {
  class PlacementServiceUnavailableError extends Error {}
  return { runRealPlacement: vi.fn(), PlacementServiceUnavailableError };
});
vi.mock('../engines/placement-service', () => placementMock);

import { handlePlacement } from '../tools/handlers/placement';
import { pcbStateCache } from '../tools/shared';

const BASE_PCB = '(kicad_pcb (net 1 "GND"))';
const PLACED_PCB = '(kicad_pcb (net 1 "GND") (placed yes))';
const PROJECT = 'p1';

const CACHED_SCHEMA = { components: [{ ref: 'R1' }, { ref: 'R2' }], nets: [{ name: 'GND' }] };
const INPUT_SCHEMA = { components: [{ ref: 'U1' }], nets: [{ name: 'VCC' }] };

beforeEach(() => {
  pcbStateCache.clear();
  engineMock.runPCBEngine.mockReset();
  engineMock.runPCBEngine.mockResolvedValue({ kicad_pcb_content: BASE_PCB });
  placementMock.runRealPlacement.mockReset();
  placementMock.runRealPlacement.mockResolvedValue({
    positions: [{ ref: 'R1', x_mm: 10, y_mm: 20 }],
    kicadPcbContent: PLACED_PCB,
  });
});

function seedCache(overrides: Record<string, unknown> = {}) {
  pcbStateCache.set(PROJECT, {
    schema: CACHED_SCHEMA,
    boardW: 60,
    boardH: 45,
    ...overrides,
  } as never);
}

/** Le schéma réellement retenu est celui passé au moteur de génération du board. */
function schemaGivenToEngine(): { components: unknown[] } {
  return engineMock.runPCBEngine.mock.calls[0]?.[0] as { components: unknown[] };
}

describe('résolution du schéma en cascade', () => {
  it('utilise schema_json quand il est valide', async () => {
    seedCache();

    await handlePlacement({ schema_json: JSON.stringify(INPUT_SCHEMA) }, PROJECT);

    expect(schemaGivenToEngine().components).toHaveLength(1);
  });

  it.each([
    ['JSON syntaxiquement invalide', '{"components": ['],
    ['tableau components vide', '{"components": [], "nets": []}'],
    ['clé components absente', '{"nets": []}'],
    ['components non-tableau', '{"components": "R1"}'],
    ['JSON null', 'null'],
    ['champ absent', undefined],
  ])('retombe sur le schéma du cache — %s', async (_label, schemaJson) => {
    seedCache();

    await handlePlacement(schemaJson === undefined ? {} : { schema_json: schemaJson }, PROJECT);

    expect(schemaGivenToEngine().components).toHaveLength(CACHED_SCHEMA.components.length);
  });

  it('sans cache ni input valide → schéma vide, aucun placement inventé', async () => {
    const result = await handlePlacement({}, PROJECT);

    expect(schemaGivenToEngine().components).toHaveLength(0);
    expect(result['placements']).toEqual([]);
    expect(placementMock.runRealPlacement).not.toHaveBeenCalled();
  });
});

describe('résolution des dimensions du board', () => {
  it('l’input est prioritaire sur le cache', async () => {
    seedCache();

    const result = await handlePlacement(
      { board_width_mm: 100, board_height_mm: 80 },
      PROJECT,
    );

    expect(result['board_width_mm']).toBe(100);
    expect(result['board_height_mm']).toBe(80);
  });

  it('le cache prend le relais quand l’input ne fournit rien', async () => {
    seedCache();

    const result = await handlePlacement({}, PROJECT);

    expect(result['board_width_mm']).toBe(60);
    expect(result['board_height_mm']).toBe(45);
  });

  it('défaut 50×40 mm sans input ni cache', async () => {
    const result = await handlePlacement({}, PROJECT);

    expect(result['board_width_mm']).toBe(50);
    expect(result['board_height_mm']).toBe(40);
  });
});

describe('board envoyé au service pcbnew', () => {
  /**
   * `call_agent_gen_pcb` produit un board via le service (kicad-tools /
   * pcbnew). `handlePlacement` le REMPLAÇAIT systématiquement par un board
   * régénéré avec le générateur TS de repli (`runPCBEngine` →
   * `runCircuitSynthEngine`, purement TypeScript, sans appel service).
   *
   * Découvert le 2026-07-27 par le test d'intégration live : le service
   * renvoyait `500 ParseError: Unexpected end of input` — il n'arrivait même
   * pas à parser le board TS. `handleRouting` évite déjà ce piège
   * explicitement ; le placement doit faire pareil.
   */
  it('utilise le board du cache produit par gen_pcb, sans le régénérer', async () => {
    seedCache({ kicad_pcb_content: '(kicad_pcb (net 0 "") (service yes))' });

    await handlePlacement({}, PROJECT);

    expect(engineMock.runPCBEngine).not.toHaveBeenCalled();
    const sent = placementMock.runRealPlacement.mock.calls[0]?.[0] as { kicadPcbContent: string };
    expect(sent.kicadPcbContent).toContain('(service yes)');
  });

  it('régénère seulement sur cache froid (placement appelé seul)', async () => {
    pcbStateCache.set(PROJECT, { schema: CACHED_SCHEMA, boardW: 60, boardH: 45 } as never);

    await handlePlacement({}, PROJECT);

    expect(engineMock.runPCBEngine).toHaveBeenCalledTimes(1);
  });
});

describe('placement nominal via pcbnew', () => {
  it('mappe les positions du service et normalise rotation/face', async () => {
    seedCache();
    placementMock.runRealPlacement.mockResolvedValue({
      positions: [
        { ref: 'R1', x_mm: 10, y_mm: 20 },
        { ref: 'U1', x_mm: 30.5, y_mm: 12.25 },
      ],
      kicadPcbContent: PLACED_PCB,
    });

    const result = await handlePlacement({}, PROJECT);

    expect(result['engine']).toBe('pcbnew');
    expect(result['pcb_status']).toBe('PLACEMENT_DONE');
    expect(result['placements']).toEqual([
      { ref: 'R1', x_mm: 10, y_mm: 20, rotation: 0, side: 'front' },
      { ref: 'U1', x_mm: 30.5, y_mm: 12.25, rotation: 0, side: 'front' },
    ]);
  });

  it('persiste le board placé et les dimensions retenues en cache', async () => {
    seedCache();

    await handlePlacement({ board_width_mm: 70 }, PROJECT);

    const entry = pcbStateCache.get(PROJECT);
    expect(entry?.kicad_pcb_content).toBe(PLACED_PCB);
    expect(entry?.boardW).toBe(70);
  });
});

describe('fail fast quand le service pcbnew est indisponible', () => {
  it('renvoie status:error — jamais un placement de repli inventé', async () => {
    seedCache();
    placementMock.runRealPlacement.mockRejectedValue(
      new placementMock.PlacementServiceUnavailableError('conteneur KiCad arrêté'),
    );

    const result = await handlePlacement({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['error']).toBe('conteneur KiCad arrêté');
    expect(result).not.toHaveProperty('placements');
    expect(result).not.toHaveProperty('kicad_pcb_content');
  });

  it('ne corrompt pas le cache avec un board non placé', async () => {
    seedCache({ kicad_pcb_content: 'BOARD_PRECEDENT' });
    placementMock.runRealPlacement.mockRejectedValue(new Error('timeout'));

    await handlePlacement({}, PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe('BOARD_PRECEDENT');
  });

  it('mentionne KICAD_SERVICE_URL pour orienter le diagnostic', async () => {
    seedCache();
    placementMock.runRealPlacement.mockRejectedValue(new Error('boom'));

    const result = await handlePlacement({}, PROJECT);

    expect(String(result['note'])).toContain('KICAD_SERVICE_URL');
  });
});
