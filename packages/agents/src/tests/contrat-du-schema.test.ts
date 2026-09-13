import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

/**
 * Le contrat de schéma, durci le 2026-09-13 après le run 25a6853c : un board
 * « 100 % routé, 0 erreur » dont le bus I2C n'existait pas — la net SDA
 * n'avait qu'une broche, parce que le filtre de broches comptait 2 pastilles
 * pour tout footprint inconnu (`PinHeader_1x04` compris) et effaçait les
 * broches 3 et 4 du connecteur. Le DRC ne voit pas une net à une broche.
 */
vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});
const haikuMock = vi.hoisted(() => ({ generateSchemaWithHaiku: vi.fn() }));
vi.mock('../tools/handlers/schema-haiku', () => haikuMock);
const claudeMock = vi.hoisted(() => ({ generateSchemaWithClaudeCode: vi.fn() }));
vi.mock('../tools/handlers/schema-claude-code', () => claudeMock);
const engineMock = vi.hoisted(() => ({ runCircuitSynthEngine: vi.fn(), runPCBEngine: vi.fn() }));
vi.mock('../engines/engine-router', () => engineMock);

import { padsDuFootprint, problemesDuSchema, parseSchemaText, messageUtilisateur, REFERENCE_KICAD } from '../tools/handlers/schema-prompt';
import { handleSchema } from '../tools/handlers/schema';
import { pcbStateCache } from '../tools/shared';

describe('padsDuFootprint — le compte se LIT dans le nom', () => {
  it('lit les grilles, les boîtiers et les clés courtes', () => {
    expect(padsDuFootprint('Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical')).toBe(4);
    expect(padsDuFootprint('Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical')).toBe(30);
    expect(padsDuFootprint('Package_QFP:LQFP-48_7x7mm_P0.5mm')).toBe(48);
    expect(padsDuFootprint('Package_SO:SOIC-8_3.9x4.9mm_P1.27mm')).toBe(8);
    expect(padsDuFootprint('Package_TO_SOT_SMD:SOT-223-3_TabPin2')).toBe(3);
    expect(padsDuFootprint('Package_TO_SOT_SMD:SOT-23-5')).toBe(5);
    expect(padsDuFootprint('Resistor_SMD:R_0603_1608Metric')).toBe(2);
    expect(padsDuFootprint('0603')).toBe(2);
    expect(padsDuFootprint('LED')).toBe(2);
    expect(padsDuFootprint('Conn_4')).toBe(4);
    expect(padsDuFootprint('TO-220')).toBe(3);
  });
  it('rend null quand le nom ne dit rien — on ne filtre pas à l aveugle', () => {
    expect(padsDuFootprint('Sensor:TMP102')).toBeNull();
    expect(padsDuFootprint('')).toBeNull();
  });
});

describe('parseSchemaText — les broches d un connecteur 1x04 survivent', () => {
  it('garde la broche 3 de SDA (elle était effacée, la net finissait à une broche)', () => {
    const texte = JSON.stringify({
      components: [
        { ref: 'J1', value: 'I2C', footprint: 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', symbol: 'Connector_Generic:Conn_01x04' },
        { ref: 'R1', value: '4.7k', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' },
      ],
      nets: ['SDA'],
      connections: [{ name: 'SDA', pins: [{ ref: 'J1', pin: 3 }, { ref: 'R1', pin: 2 }] }],
    });
    const s = parseSchemaText(texte)!;
    expect(s.connections![0]!.pins).toHaveLength(2);
  });
  it('un footprint inconnu ne perd aucune broche numérotée', () => {
    const texte = JSON.stringify({
      components: [{ ref: 'U1', value: 'X', footprint: 'Mystere:Boitier', symbol: 'Device:R' }, { ref: 'R1', value: '1k', footprint: '0603', symbol: 'Device:R' }],
      nets: ['A'],
      connections: [{ name: 'A', pins: [{ ref: 'U1', pin: 7 }, { ref: 'R1', pin: 1 }] }],
    });
    expect(parseSchemaText(texte)!.connections![0]!.pins).toHaveLength(2);
  });
});

describe('problemesDuSchema — ce que le DRC ne voit pas', () => {
  it('nomme une net à une broche et un connecteur dont le footprint ne suit pas le symbole', () => {
    const p = problemesDuSchema({
      components: [
        { ref: 'J1', value: 'I2C', footprint: 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical', symbol: 'Connector_Generic:Conn_01x04' },
        { ref: 'R1', value: '4.7k', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' },
      ],
      nets: ['SDA', 'GND'],
      connections: [
        { name: 'SDA', pins: [{ ref: 'R1', pin: 2 }] },
        { name: 'GND', pins: [{ ref: 'J1', pin: 2 }, { ref: 'R1', pin: 1 }] },
      ],
    });
    expect(p).toHaveLength(2);
    expect(p[0]).toContain('net "SDA" has 1 pin(s)');
    expect(p[1]).toContain('J1');
  });
  it('refuse une référence qui n est pas une référence KiCad (U_TMP1 débordait de son empreinte)', () => {
    const p = problemesDuSchema({
      components: [
        { ref: 'U_TMP1', value: 'TMP102', footprint: 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', symbol: 'Connector_Generic:Conn_01x04' },
        { ref: 'R1', value: '4.7k', footprint: '0603', symbol: 'Device:R' },
      ],
      nets: ['A'],
      connections: [{ name: 'A', pins: [{ ref: 'U_TMP1', pin: 1 }, { ref: 'R1', pin: 1 }] }],
    });
    expect(p).toHaveLength(1);
    expect(p[0]).toContain('"U_TMP1"');
    for (const bon of ['U1', 'C12', 'J2', 'SW1', 'Y1', 'RN3']) expect(REFERENCE_KICAD.test(bon)).toBe(true);
    for (const mauvais of ['U_TMP1', 'SENSOR', 'u1', 'U', '1', 'U1A']) expect(REFERENCE_KICAD.test(mauvais)).toBe(false);
  });

  it('un schéma sain n a aucun problème', () => {
    expect(problemesDuSchema({
      components: [{ ref: 'J1', value: 'PWR', footprint: 'Conn_2', symbol: 'Connector_Generic:Conn_01x02' }, { ref: 'R1', value: '1k', footprint: '0603', symbol: 'Device:R' }],
      nets: ['A', 'B'],
      connections: [{ name: 'A', pins: [{ ref: 'J1', pin: 1 }, { ref: 'R1', pin: 1 }] }, { name: 'B', pins: [{ ref: 'J1', pin: 2 }, { ref: 'R1', pin: 2 }] }],
    })).toEqual([]);
  });
});

describe('le second essai porte les problèmes, puis on refuse', () => {
  const BON = {
    components: [{ ref: 'J1', value: 'PWR', footprint: 'Conn_2', symbol: 'Connector_Generic:Conn_01x02' }, { ref: 'R1', value: '1k', footprint: '0603', symbol: 'Device:R' }],
    nets: ['A', 'B'],
    connections: [{ name: 'A', pins: [{ ref: 'J1', pin: 1 }, { ref: 'R1', pin: 1 }] }, { name: 'B', pins: [{ ref: 'J1', pin: 2 }, { ref: 'R1', pin: 2 }] }],
  };
  const MAUVAIS = { ...BON, connections: [{ name: 'A', pins: [{ ref: 'R1', pin: 1 }] }, BON.connections[1]!] };

  beforeEach(() => {
    vi.clearAllMocks();
    pcbStateCache.clear();
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_sch_content: '(kicad_sch)' });
  });
  afterEach(() => { delete process.env['CIRQIX_SCHEMA_PROVIDER']; });

  it('messageUtilisateur relaie les problèmes au modèle', () => {
    expect(messageUtilisateur('x')).toBe('Circuit: x');
    expect(messageUtilisateur('x', '- net "SDA" has 1 pin(s)')).toContain('rejected');
  });

  it('Haiku : un premier schéma invalide déclenche UN second essai avec les problèmes ; le second, sain, est retenu', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValueOnce(MAUVAIS).mockResolvedValueOnce(BON);
    const r = await handleSchema({ user_description: 'un truc' }, 'p1');
    expect(r['status']).toBe('success');
    expect(haikuMock.generateSchemaWithHaiku).toHaveBeenCalledTimes(2);
    expect(String(haikuMock.generateSchemaWithHaiku.mock.calls[1]![1])).toContain('net "A" has 1 pin(s)');
  });

  it('Claude Code : même règle, le retour passe en troisième argument', async () => {
    process.env['CIRQIX_SCHEMA_PROVIDER'] = 'claude-code';
    claudeMock.generateSchemaWithClaudeCode.mockResolvedValueOnce(MAUVAIS).mockResolvedValueOnce(BON);
    const r = await handleSchema({ user_description: 'un truc' }, 'p2');
    expect(r['status']).toBe('success');
    expect(claudeMock.generateSchemaWithClaudeCode).toHaveBeenCalledTimes(2);
    expect(String(claudeMock.generateSchemaWithClaudeCode.mock.calls[1]![2])).toContain('net "A" has 1 pin(s)');
  });

  it('deux schémas invalides : le run est REFUSÉ et nomme le problème — rien n est fabriqué', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValue(MAUVAIS);
    const r = await handleSchema({ user_description: 'un truc' }, 'p3');
    expect(r['status']).toBe('error');
    expect(String(r['error'])).toContain('net "A" has 1 pin(s)');
    expect(engineMock.runCircuitSynthEngine).not.toHaveBeenCalled();
  });

  it('un schéma sain du premier coup : un seul appel', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValue(BON);
    await handleSchema({ user_description: 'un truc' }, 'p4');
    expect(haikuMock.generateSchemaWithHaiku).toHaveBeenCalledTimes(1);
  });
});

describe('l enrichissement des footprints', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pcbStateCache.clear();
    engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_sch_content: '(kicad_sch)' });
  });
  it('ne réécrit JAMAIS un footprint déjà qualifié Lib:Nom (J1 1x04 restait 1x02 dans l état publié)', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValue({
      components: [
        { ref: 'J1', value: 'I2C', footprint: 'Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical', symbol: 'Connector_Generic:Conn_01x04' },
        { ref: 'R1', value: '1k', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' },
      ],
      nets: ['A', 'B'],
      connections: [{ name: 'A', pins: [{ ref: 'J1', pin: 3 }, { ref: 'R1', pin: 1 }] }, { name: 'B', pins: [{ ref: 'J1', pin: 4 }, { ref: 'R1', pin: 2 }] }],
    });
    const r = await handleSchema({ user_description: 'x' }, 'p9');
    const j1 = (r['components'] as Array<{ ref: string; footprint: string }>).find((c) => c.ref === 'J1')!;
    expect(j1.footprint).toBe('Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical');
  });
});
