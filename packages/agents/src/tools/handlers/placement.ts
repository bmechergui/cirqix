import { pcbStateCache, log } from '../shared';
import { runPCBEngine } from '../../engines/engine-router';
import type { SchemaJson } from '../../engines/engine-router';
import { runRealPlacement } from '../../engines/placement-service';

export async function handlePlacement(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  // Use dimensions from schema cache (set by call_agent_schema) when caller
  // doesn't supply explicit board dimensions — ensures adaptive sizing holds.
  const cachedDims = pcbStateCache.get(projectId);
  const boardW = Number(input['board_width_mm'] ?? cachedDims?.boardW ?? 50);
  const boardH = Number(input['board_height_mm'] ?? cachedDims?.boardH ?? 40);

  // Parse schema_json from input if provided. Fall back to the cached schema
  // from call_agent_schema if the agent passes nothing valid here.
  let schema: SchemaJson;
  try {
    const parsed: unknown = JSON.parse(String(input['schema_json'] ?? '{}'));
    if (
      typeof parsed !== 'object' ||
      parsed === null ||
      !Array.isArray((parsed as Record<string, unknown>)['components']) ||
      ((parsed as { components: unknown[] }).components.length === 0)
    ) {
      throw new Error('invalid or empty schema_json');
    }
    schema = parsed as SchemaJson;
  } catch {
    const cached = pcbStateCache.get(projectId);
    schema = cached?.schema ?? { components: [], nets: [] };
  }

  // Refresh the .kicad_pcb with the requested board size via Circuit-Synth.
  // This guarantees we always have a valid native file to ship to the viewer,
  // regardless of whether the pcbnew placement service succeeds.
  const base = await runPCBEngine(schema, boardW, boardH, projectId);

  // Empty schema → return early with no placements
  if (schema.components.length === 0) {
    pcbStateCache.set(projectId, {
      schema, boardW, boardH, kicad_pcb_content: base.kicad_pcb_content,
    });
    return {
      status: 'success',
      pcb_status: 'PLACEMENT_DONE',
      placements: [],
      kicad_pcb_content: base.kicad_pcb_content,
      board_width_mm: boardW,
      board_height_mm: boardH,
      engine: 'fallback-ts',
      note: `Placement — schéma vide.`,
    };
  }

  // Try the real pcbnew placement service first; fall back to the pure
  // TS planner on any error so the agentic loop stays alive offline.
  try {
    const service = await runRealPlacement({
      kicadPcbContent: base.kicad_pcb_content,
      boardWidthMm: boardW,
      boardHeightMm: boardH,
    });
    const placements = service.positions.map((p) => ({
      ref: p.ref,
      x_mm: p.x_mm,
      y_mm: p.y_mm,
      rotation: 0,
      side: 'front',
    }));
    pcbStateCache.set(projectId, {
      schema, boardW, boardH, kicad_pcb_content: service.kicadPcbContent,
    });
    return {
      status: 'success',
      pcb_status: 'PLACEMENT_DONE',
      placements,
      kicad_pcb_content: service.kicadPcbContent,
      board_width_mm: boardW,
      board_height_mm: boardH,
      engine: 'pcbnew',
      note: `Placement pcbnew — PCB ${boardW}×${boardH} mm, ${placements.length} composants.`,
    };
  } catch (err) {
    log.error({ err, projectId }, 'placement service unavailable');
    return {
      status: 'error',
      error: err instanceof Error ? err.message : 'placement service unavailable',
      note: 'Service pcbnew inaccessible — vérifie que le conteneur Docker KiCad tourne (KICAD_SERVICE_URL).',
    };
  }
}
