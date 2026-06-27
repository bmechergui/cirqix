import pino from 'pino';
import type { SimulationData, SimulationVector } from '@cirqix/types';

const log = pino({ name: 'cirqix.agents.simulation-service', level: process.env['LOG_LEVEL'] ?? 'info' });

export class SimulationServiceUnavailableError extends Error {
  constructor(msg: string) {
    super(msg);
    this.name = 'SimulationServiceUnavailableError';
  }
}

export interface SimulationOptions {
  kicadSchContent: string;
  simType?: 'transient' | 'dc' | 'ac';
}

export interface SimulationResult {
  data: SimulationData;
  skipped: boolean;
  warning?: string;
}

export async function runSimulation(opts: SimulationOptions): Promise<SimulationResult> {
  const { kicadSchContent, simType = 'transient' } = opts;
  const kicadServiceUrl = process.env['KICAD_SERVICE_URL'];

  if (!kicadServiceUrl) {
    log.warn('KICAD_SERVICE_URL not set — returning demo simulation');
    throw new SimulationServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const b64 = Buffer.from(kicadSchContent).toString('base64');

  const res = await fetch(`${kicadServiceUrl}/simulate/auto`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kicad_sch_b64: b64, sim_type: simType }),
    signal: AbortSignal.timeout(90_000),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new SimulationServiceUnavailableError(`simulate/auto failed ${res.status}: ${text.slice(0, 200)}`);
  }

  const json = await res.json() as {
    status: string;
    sim_type: string;
    vectors: Array<{ name: string; unit: string; time: number[]; values: number[] }>;
  };

  if (json.status !== 'ok' || !Array.isArray(json.vectors)) {
    throw new SimulationServiceUnavailableError(`simulate/auto returned invalid payload`);
  }

  const vectors: SimulationVector[] = json.vectors.map((v) => ({
    name: v.name,
    unit: v.unit as SimulationVector['unit'],
    time: v.time,
    values: v.values,
  }));

  log.info({ sim_type: simType, vector_count: vectors.length }, 'simulation complete');

  return {
    data: { sim_type: simType, vectors },
    skipped: false,
  };
}
