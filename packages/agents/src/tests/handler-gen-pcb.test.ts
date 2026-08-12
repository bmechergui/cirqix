import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleGenPcb — dernier handler portant un succès fantôme.
 *
 * Quand le service Python ne renvoie rien d'exploitable ET que le générateur TS
 * de repli rend une chaîne vide, le handler renvoyait `status:'success'` avec
 * `kicad_pcb_content: ''` et promouvait même `pcb_status: 'ERC_CLEAN'`.
 * Découvert le 2026-07-27 par le test d'intégration live : sans `.kicad_sch` en
 * cache, `generate_pcb` court-circuite ses deux niveaux Python et rend "" — le
 * handler annonçait pourtant un succès. Le placement échouait ensuite sur un
 * board vide, en masquant la vraie cause.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const engineMock = vi.hoisted(() => ({
  runCircuitSynthEngine: vi.fn(),
  runPCBEngine: vi.fn(),
}));
vi.mock('../engines/engine-router', () => engineMock);

vi.mock('../engines/kicad-service-auth', () => ({
  buildKicadServiceHeaders: () => ({ 'Content-Type': 'application/json' }),
}));

import { handleGenPcb } from '../tools/handlers/gen-pcb';
import { pcbStateCache } from '../tools/shared';

const PROJECT = 'p1';
const SCHEMA = { components: [{ ref: 'R1', value: '1k' }], nets: ['GND'], connections: [] };

beforeEach(() => {
  pcbStateCache.clear();
  delete process.env['KICAD_SERVICE_URL'];
  engineMock.runCircuitSynthEngine.mockReset();
  engineMock.runPCBEngine.mockReset();
});

function seed() {
  pcbStateCache.set(PROJECT, { schema: SCHEMA, boardW: 50, boardH: 40 } as never);
}

describe('génération réussie', () => {
  it('renvoie le board produit par le générateur TS', async () => {
    seed();
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_pcb_content: '(kicad_pcb (net 0 ""))' });

    const result = await handleGenPcb(PROJECT);

    expect(result['status']).toBe('success');
    expect(String(result['kicad_pcb_content'])).toContain('(kicad_pcb');
    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toContain('(kicad_pcb');
  });

  it("n'émet AUCUN pcb_status — générer un layout ne change pas l'état de validation", async () => {
    seed();
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_pcb_content: '(kicad_pcb (net 0 ""))' });

    const result = await handleGenPcb(PROJECT);

    // Le handler émettait `SCHEMA_DONE` inconditionnellement. Or le pipeline le
    // place APRÈS l'ERC : un projet porté à `ERC_CLEAN` RÉTROGRADAIT donc à
    // `SCHEMA_DONE`, et le pont persistait ce recul. Si le run mourait là,
    // l'état affiché oubliait un contrôle électrique réellement passé.
    //
    // L'intention était pourtant écrite — « un layout ne prouve rien
    // d'électrique ». Ne RIEN émettre en est la traduction fidèle : le pont
    // fait `raw.pcb_status ?? lastStatus`, donc SCHEMA_DONE reste SCHEMA_DONE
    // et ERC_CLEAN reste ERC_CLEAN.
    //
    // Trouvé le 2026-08-12 par un audit externe (Grok).
    expect(result['pcb_status']).toBeUndefined();
    expect(result['status']).toBe('success');
  });
});

describe('jamais de succès sur un board vide', () => {
  it('board vide → erreur, pas un succès avec ERC_CLEAN', async () => {
    seed();
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_pcb_content: '' });

    const result = await handleGenPcb(PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('ERC_CLEAN');
  });

  it('ne met pas un board vide en cache — le placement échouerait sans cause lisible', async () => {
    pcbStateCache.set(PROJECT, {
      schema: SCHEMA, boardW: 50, boardH: 40, kicad_pcb_content: 'BOARD_PRECEDENT',
    } as never);
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_pcb_content: '' });

    await handleGenPcb(PROJECT);

    expect(pcbStateCache.get(PROJECT)?.kicad_pcb_content).toBe('BOARD_PRECEDENT');
  });

  it('schéma absent → erreur (comportement existant, verrouillé)', async () => {
    const result = await handleGenPcb(PROJECT);

    expect(result['status']).toBe('error');
  });
});

