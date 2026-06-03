import { pcbStateCache, log } from '../shared';
import { runSimulation, SimulationServiceUnavailableError } from '../../engines/simulation-service';

export async function handleSimulation(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const simType = (input['sim_type'] as 'transient' | 'dc' | 'ac' | undefined) ?? 'transient';
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
