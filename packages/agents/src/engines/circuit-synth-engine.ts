/**
 * Circuit-Synth engine — calls the KiCad service to convert a JSON schema
 * into native .kicad_sch + .kicad_pcb files.
 *
 * The KiCad service generates the files server-side (pcbnew Python API or
 * S-expression fallback) and returns the file contents as strings.
 * These are then uploaded to Supabase Storage by the agent route.
 */

import type { SchemaJson } from './tscircuit-engine';

export interface CircuitSynthResult {
  kicad_sch_content: string | null;
  kicad_pcb_content: string | null;
}

interface ServiceResponse {
  success: boolean;
  kicad_sch_content?: string | null;
  kicad_pcb_content?: string | null;
  error?: string;
}

/**
 * Returns true when KICAD_SERVICE_URL is configured — i.e. the service is
 * expected to be reachable. Does not perform a network check.
 */
export function isCircuitSynthAvailable(): boolean {
  return Boolean(process.env.KICAD_SERVICE_URL);
}

/**
 * Call the /circuit-synth/generate endpoint and return native KiCad file contents.
 * Throws if the service is unreachable or returns a non-2xx status.
 */
export async function runCircuitSynthEngine(
  schema: SchemaJson,
  boardWidthMm = 50,
  boardHeightMm = 50,
  projectId = ''
): Promise<CircuitSynthResult> {
  const baseUrl = process.env.KICAD_SERVICE_URL ?? 'http://localhost:8000';

  const res = await fetch(`${baseUrl}/circuit-synth/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      components: schema.components,
      nets: schema.nets,
      connections: schema.connections ?? [],
      board_width_mm: boardWidthMm,
      board_height_mm: boardHeightMm,
      project_id: projectId,
    }),
    signal: AbortSignal.timeout(30_000), // 30s timeout
  });

  if (!res.ok) {
    throw new Error(`Circuit-Synth service returned ${res.status}`);
  }

  const data = (await res.json()) as ServiceResponse;

  if (!data.success) {
    throw new Error(data.error ?? 'Circuit-Synth generation failed');
  }

  return {
    kicad_sch_content: data.kicad_sch_content ?? null,
    kicad_pcb_content: data.kicad_pcb_content ?? null,
  };
}
