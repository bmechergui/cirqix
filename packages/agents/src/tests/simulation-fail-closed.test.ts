import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * La simulation ne doit JAMAIS fabriquer un succès (issue #129).
 *
 * `handleSimulation` était le dernier handler du pipeline à renvoyer
 * `status: 'success'` avec des données inventées quand son service est absent :
 * une courbe RC synthétique, plausible, jamais calculée à partir du circuit de
 * l'utilisateur. Les champs `engine: 'demo'` et `warning` étaient présents —
 * exactement les indices qu'une interface graphique n'affiche pas.
 *
 * C'est la classe de défaut fondatrice de ce projet, éliminée partout ailleurs
 * (ERC, DRC, routage, export). Le risque n'est pas financier : c'est une
 * décision de conception prise sur une mesure inventée.
 */

const simulationMock = vi.hoisted(() => {
  class SimulationServiceUnavailableError extends Error {}
  return { runSimulation: vi.fn(), SimulationServiceUnavailableError };
});
vi.mock('../engines/simulation-service', () => simulationMock);

import { handleSimulation } from '../tools/handlers/simulation';
import { pcbStateCache, setProjectPlan, clearProjectPlan } from '../tools/shared';

const PROJECT = 'p-sim-fc';

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.clear();
  clearProjectPlan(PROJECT);
  delete process.env['CIRQIX_SIMULATION_DEMO'];
  setProjectPlan(PROJECT, 'pro');
  pcbStateCache.set(PROJECT, {
    schema: { components: [], nets: [] },
    boardW: 50,
    boardH: 50,
    kicad_sch_content: '(kicad_sch)',
  } as never);
});

afterEach(() => {
  delete process.env['CIRQIX_SIMULATION_DEMO'];
});

describe('handleSimulation — jamais de succès sans simulation réelle', () => {
  it.each([
    ['service injoignable', () => new simulationMock.SimulationServiceUnavailableError('ngspice absent')],
    ['erreur inattendue', () => new Error('boom')],
  ])('%s → status error, aucune donnée', async (_label, makeError) => {
    simulationMock.runSimulation.mockRejectedValue(makeError());

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(result['simulation_data']).toBeUndefined();
    expect(result['vector_count']).toBeUndefined();
  });

  it("dit que c'est le service qui manque, pas le circuit", async () => {
    // Un utilisateur Pro dont la simulation échoue doit pouvoir distinguer
    // « votre circuit ne se simule pas » de « notre service est indisponible ».
    // Les deux appellent des actions opposées.
    simulationMock.runSimulation.mockRejectedValue(
      new simulationMock.SimulationServiceUnavailableError('ngspice absent'),
    );

    const result = await handleSimulation({}, PROJECT);

    expect(String(result['note'])).toMatch(/indisponible|injoignable/i);
  });

  it('ne sert des données de démonstration que si on les demande EXPLICITEMENT', async () => {
    // Le mode démo garde son utilité en développement local — mais comme choix
    // affiché, jamais comme repli silencieux sur erreur.
    process.env['CIRQIX_SIMULATION_DEMO'] = '1';
    simulationMock.runSimulation.mockRejectedValue(
      new simulationMock.SimulationServiceUnavailableError('ngspice absent'),
    );

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('success');
    expect(result['engine']).toBe('demo');
    expect(result['simulation_data']).toBeDefined();
  });

  it('le mode démo doit être armé — une valeur vide ne suffit pas', async () => {
    process.env['CIRQIX_SIMULATION_DEMO'] = '';
    simulationMock.runSimulation.mockRejectedValue(new Error('boom'));

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('error');
  });

  it('un succès réel reste un succès', async () => {
    simulationMock.runSimulation.mockResolvedValue({
      data: { sim_type: 'transient', vectors: [{ name: 'V(out)', values: [1, 2] }] },
    });

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('success');
    expect(result['vector_count']).toBe(1);
    expect(result['engine']).toBeUndefined(); // pas 'demo'
  });
});
