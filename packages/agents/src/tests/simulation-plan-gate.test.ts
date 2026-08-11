import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * La simulation est-elle réellement réservée aux plans payants ?
 *
 * `PLAN_ENTITLEMENTS.canSimulate` existait depuis la PR #126 mais rien ne le
 * lisait : la table décrivait un droit que personne n'appliquait. C'est le
 * second point d'application serveur du plan, après le plafond de couches.
 *
 * Le contrôle est ici, dans le handler, et non dans le prompt de l'orchestrateur :
 * un modèle à qui l'on demande de ne pas appeler un outil finit toujours par
 * l'appeler. Le refus doit être structurel.
 */

const simulationMock = vi.hoisted(() => {
  class SimulationServiceUnavailableError extends Error {}
  return { runSimulation: vi.fn(), SimulationServiceUnavailableError };
});
vi.mock('../engines/simulation-service', () => simulationMock);

import { handleSimulation } from '../tools/handlers/simulation';
import { pcbStateCache, setProjectPlan, clearProjectPlan } from '../tools/shared';

const PROJECT = 'p-sim';

function seedSchema() {
  pcbStateCache.set(PROJECT, {
    schema: { components: [], nets: [] },
    boardW: 50,
    boardH: 50,
    kicad_sch_content: '(kicad_sch)',
  } as never);
}

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.clear();
  clearProjectPlan(PROJECT);
  simulationMock.runSimulation.mockResolvedValue({
    data: { sim_type: 'transient', vectors: [{ name: 'V(out)', values: [] }] },
  });
  seedSchema();
});

describe('handleSimulation — droit lié au plan', () => {
  it('refuse un compte gratuit sans appeler le service', async () => {
    setProjectPlan(PROJECT, 'free');

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(simulationMock.runSimulation).not.toHaveBeenCalled();
  });

  it('laisse simuler un compte Pro', async () => {
    setProjectPlan(PROJECT, 'pro');

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('success');
    expect(simulationMock.runSimulation).toHaveBeenCalledTimes(1);
  });

  it('refuse quand le plan est absent — le défaut ne doit pas ouvrir de droit', async () => {
    // Une omission de plumbing ne doit jamais offrir une fonctionnalité
    // payante. Même repli fail-closed que le plafond de couches.
    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(simulationMock.runSimulation).not.toHaveBeenCalled();
  });

  it("ne renvoie JAMAIS de données de démonstration sur un refus de plan", async () => {
    // Le chemin de repli du handler fabrique des vecteurs synthétiques quand
    // ngspice est absent. Les servir sur un refus de plan donnerait au compte
    // gratuit exactement ce qu'il n'a pas payé, sous une étiquette « démo ».
    setProjectPlan(PROJECT, 'free');

    const result = await handleSimulation({}, PROJECT);

    expect(result['simulation_data']).toBeUndefined();
    expect(result['vector_count']).toBeUndefined();
  });

  it('dit quel plan débloque la fonctionnalité', async () => {
    // Un refus qui n'indique pas la sortie est un cul-de-sac : l'utilisateur
    // ne sait pas s'il doit acheter des crédits, changer de plan, ou attendre.
    setProjectPlan(PROJECT, 'free');

    const result = await handleSimulation({}, PROJECT);

    expect(String(result['note'])).toMatch(/pro/i);
  });

  it('ne masque pas un schéma manquant derrière le refus de plan', async () => {
    // Sur un plan payant, l'absence de schéma reste l'erreur qu'elle était :
    // le contrôle de droit ne doit pas avaler les diagnostics existants.
    pcbStateCache.clear();
    setProjectPlan(PROJECT, 'pro');

    const result = await handleSimulation({}, PROJECT);

    expect(result['status']).toBe('error');
    expect(String(result['note'])).toContain('schéma');
  });
});
