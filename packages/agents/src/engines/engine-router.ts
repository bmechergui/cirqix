/**
 * Engine router — Circuit-Synth is the only engine.
 * TSCircuit is permanently removed.
 */

import { runCircuitSynthEngine, isCircuitSynthAvailable } from './schematic-engine';
export type { CircuitSynthResult } from './schematic-engine';
export { isCircuitSynthAvailable, runCircuitSynthEngine };

// Re-export schema types for consumers
export type { SchemaJson } from '@cirqix/types';

export type PCBEngine = 'circuit-synth';

export interface PCBEngineResult {
  engine: PCBEngine;
  kicad_sch_content: string;
  kicad_pcb_content: string;
  /** Component placements for chat summary */
  placements: Array<{ ref: string; x_mm: number; y_mm: number; rotation: number; side: string }>;
  boardWidthMm: number;
  boardHeightMm: number;
}

/** Always circuit-synth */
export function selectEngine(): PCBEngine {
  return 'circuit-synth';
}

/**
 * Run Circuit-Synth and return KiCad files + grid placement summary.
 * Real pcbnew placement is applied by call_agent_placement in tools.ts;
 * the grid here is only used as a fallback base for downstream steps.
 */
export async function runPCBEngine(
  schema: import('@cirqix/types').SchemaJson,
  boardWidthMm = 50,
  boardHeightMm = 50,
  projectId = ''
): Promise<PCBEngineResult> {
  const result = await runCircuitSynthEngine(schema, boardWidthMm, boardHeightMm, projectId);

  const cols = Math.max(1, Math.ceil(Math.sqrt(schema.components.length)));
  const margin = 5;
  const usableW = boardWidthMm - 2 * margin;
  const usableH = boardHeightMm - 2 * margin;
  const rows = Math.ceil(schema.components.length / cols);
  const placements = schema.components.map((comp, i) => ({
    ref: comp.ref,
    x_mm: +(margin + (i % cols + 0.5) * (usableW / cols)).toFixed(1),
    y_mm: +(margin + (Math.floor(i / cols) + 0.5) * (usableH / rows)).toFixed(1),
    rotation: 0,
    side: 'front',
  }));

  return {
    engine: 'circuit-synth',
    kicad_sch_content: result.kicad_sch_content,
    kicad_pcb_content: result.kicad_pcb_content,
    placements,
    boardWidthMm,
    boardHeightMm,
  };
}
