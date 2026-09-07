import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * `call_agent_schema` doit pouvoir travailler SANS appeler le moindre modèle.
 *
 * Le solde de l'API Anthropic est épuisé depuis le 2026-09-06 : l'orchestrateur
 * étant la première étape, plus aucun pipeline ne peut aboutir par la voie
 * normale, et `handleSchema` est le SEUL maillon de la chaîne qui appelle un
 * modèle. Tout le reste — ERC, gen_pcb, placement, routage, DRC, export — est
 * déterministe, et le banc des dix cartes l'a prouvé jusqu'aux Gerbers.
 *
 * On ouvre donc une entrée `schema_json` : le schéma est écrit par le driver
 * (Claude Code joue l'Ingénieur Schéma), et le reste du chemin est INCHANGÉ —
 * `/schematic/generate`, l'enrichissement des footprints, l'écriture du cache.
 *
 * ⚠️ Ce n'est PAS un mode simulé : le board produit est réel, mesuré par un vrai
 * DRC. C'est la provenance qui change, pas la qualité — et c'est pourquoi le
 * gate JLCPCB, qui exige `orchestrator`, continue de le refuser.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const haikuMock = vi.hoisted(() => ({ generateSchemaWithHaiku: vi.fn() }));
vi.mock('../tools/handlers/schema-haiku', () => haikuMock);

const engineMock = vi.hoisted(() => ({
  runCircuitSynthEngine: vi.fn(),
  runPCBEngine: vi.fn(),
}));
vi.mock('../engines/engine-router', () => engineMock);

import { handleSchema } from '../tools/handlers/schema';
import { pcbStateCache } from '../tools/shared';

const SCHEMA_DU_DRIVER = {
  components: [
    { ref: 'U1', value: 'STM32F103C8T6', footprint: 'Package_QFP:LQFP-48_7x7mm_P0.5mm', symbol: 'MCU_ST_STM32F1:STM32F103C8Tx' },
    { ref: 'R1', value: '1k', footprint: 'Resistor_SMD:R_0603_1608Metric', symbol: 'Device:R' },
    { ref: 'D1', value: 'LED', footprint: 'LED_SMD:LED_0603_1608Metric', symbol: 'Device:LED' },
  ],
  nets: ['GND', '+3V3', 'LEDA'],
  connections: [{ name: 'LEDA', pins: [{ ref: 'R1', pin: 2 }, { ref: 'D1', pin: 2 }] }],
};

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.clear();
  engineMock.runCircuitSynthEngine.mockResolvedValue({ kicad_sch_content: '(kicad_sch)' });
});

describe('call_agent_schema — schéma fourni par le driver', () => {
  it('n appelle AUCUN modèle quand le schéma est fourni', async () => {
    const r = await handleSchema(
      { schema_json: JSON.stringify(SCHEMA_DU_DRIVER) },
      'projet-driver',
    );

    expect(haikuMock.generateSchemaWithHaiku).not.toHaveBeenCalled();
    expect(r['status']).toBe('success');
    expect(r['pcb_status']).toBe('SCHEMA_DONE');
    expect(r['engine']).toBe('driver-json');
  });

  it('accepte aussi un objet déjà décodé', async () => {
    const r = await handleSchema({ schema_json: SCHEMA_DU_DRIVER }, 'projet-objet');
    expect(r['status']).toBe('success');
    expect(haikuMock.generateSchemaWithHaiku).not.toHaveBeenCalled();
  });

  it('remplit le cache comme le ferait le chemin normal', async () => {
    await handleSchema({ schema_json: JSON.stringify(SCHEMA_DU_DRIVER) }, 'projet-cache');

    const cache = pcbStateCache.get('projet-cache');
    expect(cache?.schema.components).toHaveLength(3);
    expect(cache?.kicad_sch_content).toBe('(kicad_sch)');
    // `call_agent_gen_pcb` produit le board — jamais ce handler.
    expect(cache?.kicad_pcb_content).toBeUndefined();
  });

  it('honore les dimensions de carte fournies par le driver', async () => {
    // ⚠️ L'heuristique par défaut plafonne à 50 x 40 mm au-delà de 12
    // composants. Le banc des dix cartes a MESURÉ que la surface est le levier :
    // `carte-08` passe de 216 connexions manquantes à ZÉRO en l'agrandissant de
    // 110x80 à 125x95, rien d'autre n'ayant changé. Un board de 70 composants
    // sur 50x40 mm est hors d'atteinte quel que soit le routeur.
    await handleSchema(
      { schema_json: { ...SCHEMA_DU_DRIVER, board_width_mm: 125, board_height_mm: 95 } },
      'projet-grand',
    );

    const cache = pcbStateCache.get('projet-grand');
    expect(cache?.boardW).toBe(125);
    expect(cache?.boardH).toBe(95);
  });

  it('garde l heuristique quand le driver ne dit rien', async () => {
    await handleSchema({ schema_json: SCHEMA_DU_DRIVER }, 'projet-defaut');
    const cache = pcbStateCache.get('projet-defaut');
    expect(cache?.boardW).toBe(30);
    expect(cache?.boardH).toBe(25);
  });

  it('ECHOUE FERME sur un schéma illisible, sans jamais en fabriquer un', async () => {
    // Le chemin Haiku refuse déjà de fabriquer un schéma sans rapport avec la
    // demande — « un ATmega328P pour un capteur de température ». Le chemin du
    // driver applique la MÊME règle : mieux vaut une erreur qu un board faux.
    for (const mauvais of ['{ ceci nest pas du json', '{}', '{"components":[]}', '[]']) {
      const r = await handleSchema({ schema_json: mauvais }, 'projet-mauvais');
      expect(r['status']).toBe('error');
      expect(pcbStateCache.has('projet-mauvais')).toBe(false);
    }
    expect(haikuMock.generateSchemaWithHaiku).not.toHaveBeenCalled();
  });

  it('un schéma sans nets est refusé', async () => {
    const r = await handleSchema(
      { schema_json: { components: SCHEMA_DU_DRIVER.components, nets: [] } },
      'projet-sans-nets',
    );
    expect(r['status']).toBe('error');
  });

  it('ne change RIEN au chemin Haiku quand aucun schéma n est fourni', async () => {
    haikuMock.generateSchemaWithHaiku.mockResolvedValue(SCHEMA_DU_DRIVER);
    const r = await handleSchema({ user_description: 'une LED' }, 'projet-haiku');

    expect(haikuMock.generateSchemaWithHaiku).toHaveBeenCalledWith('une LED');
    expect(r['status']).toBe('success');
    expect(r['engine']).toBe('circuit-synth-json');
  });
});
