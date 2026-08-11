import { pcbStateCache, log, getProjectPlan } from '../shared';
import { entitlementsForPlan } from '@cirqix/types';
import { runSimulation, SimulationServiceUnavailableError } from '../../engines/simulation-service';

export async function handleSimulation(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const simType = (input['sim_type'] as 'transient' | 'dc' | 'ac' | undefined) ?? 'transient';

  // Droit lié au plan — second point d'application serveur après le plafond de
  // couches. `canSimulate` existait dans PLAN_ENTITLEMENTS sans que rien ne le
  // lise : la table décrivait un droit que personne n'appliquait.
  //
  // Le contrôle est ICI et non dans le prompt de l'orchestrateur : un modèle à
  // qui l'on demande de ne pas appeler un outil finit par l'appeler. Le refus
  // doit être structurel.
  //
  // Placé AVANT tout le reste, et en particulier avant le repli qui fabrique
  // des vecteurs synthétiques quand ngspice est absent : servir cette « démo »
  // sur un refus de plan donnerait au compte gratuit exactement ce qu'il n'a
  // pas payé. Un plan absent refuse aussi — une omission de plumbing ne doit
  // jamais offrir une fonctionnalité payante.
  if (!entitlementsForPlan(getProjectPlan(projectId)).canSimulate) {
    return {
      status: 'error',
      note:
        'La simulation SPICE est réservée aux plans Pro et supérieurs. ' +
        'Le reste du pipeline PCB reste disponible.',
    };
  }

  const cached = pcbStateCache.get(projectId);
  const schContent = cached?.kicad_sch_content;

  if (!schContent || schContent.length === 0) {
    return {
      status: 'error',
      note: 'Pas de schéma en cache — exécute call_agent_schema en premier.',
    };
  }

  try {
    const result = await runSimulation({ kicadSchContent: schContent, simType });
    return {
      status: 'success',
      sim_type: simType,
      simulation_data: result.data,
      vector_count: result.data.vectors.length,
      note: `Simulation ${simType} — ${result.data.vectors.length} vecteurs (${result.data.vectors.map((v) => v.name).join(', ')}).`,
    };
  } catch (err) {
    if (!(err instanceof SimulationServiceUnavailableError)) {
      log.warn({ err }, 'simulation service threw unexpected error');
    }
    // Return synthetic demo data so the pipeline stays alive offline
    const demoVectors = _demoVectors(simType);
    return {
      status: 'success',
      sim_type: simType,
      simulation_data: { sim_type: simType, vectors: demoVectors },
      vector_count: demoVectors.length,
      engine: 'demo',
      warning: err instanceof Error ? err.message : 'simulation service unavailable',
      note: `Simulation démo — ${demoVectors.length} vecteurs synthétiques (ngspice indisponible).`,
    };
  }
}

// ---------------------------------------------------------------------------
// Demo simulation vectors (used when ngspice service is unavailable)
// ---------------------------------------------------------------------------

function _demoVectors(simType: string): Array<{ name: string; unit: string; time: number[]; values: number[] }> {
  const steps = 200;
  if (simType === 'ac') {
    const freqs = Array.from({ length: 70 }, (_, i) => Math.pow(10, i * 0.1));
    return [
      { name: 'v(out)', unit: 'V', time: freqs,
        values: freqs.map((f) => 1 / Math.sqrt(1 + Math.pow(f / 1592, 2))) },
    ];
  }
  const t = Array.from({ length: steps }, (_, i) => i * 1e-6);
  const tau = 1e-4;
  return [
    { name: 'v(vin)',  unit: 'V', time: t, values: Array(steps).fill(5.0) },
    { name: 'v(vmid)', unit: 'V', time: t, values: t.map((ti) => 5 * (1 - Math.exp(-ti / tau))) },
    { name: 'i(v1)',   unit: 'A', time: t, values: t.map((ti) => (5 / 1000) * Math.exp(-ti / tau)) },
  ];
}
