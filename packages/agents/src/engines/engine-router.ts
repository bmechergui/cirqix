import { runTSCircuitEngine, isSimpleCircuit } from './tscircuit-engine';
import type { SchemaJson, TSCircuitResult } from './tscircuit-engine';
import { runCircuitSynthEngine, isCircuitSynthAvailable } from './circuit-synth-engine';
export type { CircuitSynthResult } from './circuit-synth-engine';

export type { SchemaJson, TSCircuitResult };

export type PCBEngine = 'circuit-synth' | 'tscircuit' | 'kicad';

/** Decide which engine to use based on availability and complexity */
export function selectEngine(schema: SchemaJson): PCBEngine {
  if (isCircuitSynthAvailable()) return 'circuit-synth';
  return isSimpleCircuit(schema) ? 'tscircuit' : 'kicad';
}

/** Run the appropriate engine and return the result */
export async function runPCBEngine(
  schema: SchemaJson,
  boardWidthMm = 50,
  boardHeightMm = 50,
  projectId = ''
): Promise<TSCircuitResult & { engine: PCBEngine; kicad_sch_content?: string | null; kicad_pcb_content?: string | null }> {
  const engine = selectEngine(schema);

  if (engine === 'circuit-synth') {
    try {
      const result = await runCircuitSynthEngine(schema, boardWidthMm, boardHeightMm, projectId);
      return {
        engine: 'circuit-synth',
        circuitJson: [],
        gerbers: {},
        boardWidthMm,
        boardHeightMm,
        placements: schema.components.map((c, i) => ({
          ref: c.ref,
          x_mm: (i % 5) * 10 + 5,
          y_mm: Math.floor(i / 5) * 10 + 5,
          rotation: 0,
          side: 'front',
        })),
        kicad_sch_content: result.kicad_sch_content,
        kicad_pcb_content: result.kicad_pcb_content,
      };
    } catch {
      // Circuit-Synth unavailable — fall through to TSCircuit
    }
  }

  if (engine === 'circuit-synth' || engine === 'tscircuit') {
    const result = await runTSCircuitEngine(schema, boardWidthMm, boardHeightMm);
    return { ...result, engine: 'tscircuit' };
  }

  // KiCad stub — Phase 3.1
  return {
    engine: 'kicad',
    circuitJson: [],
    gerbers: {},
    boardWidthMm,
    boardHeightMm,
    placements: schema.components.map((c, i) => ({
      ref: c.ref,
      x_mm: (i % 5) * 10 + 5,
      y_mm: Math.floor(i / 5) * 10 + 5,
      rotation: 0,
      side: 'front',
    })),
  };
}

export { runCircuitSynthEngine, isCircuitSynthAvailable };
