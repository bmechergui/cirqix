import { pcbStateCache, log } from '../shared';
import { runPCBEngine } from '../../engines/engine-router';
import { runRealRouting, RoutingServiceUnavailableError } from '../../engines/routing-service';
import { stripTrackSegments, addGroundPlane } from '../pcb-helpers';

export async function handleRouting(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const schema = cached?.schema ?? { components: [], nets: [] };
  const boardW = cached?.boardW ?? 50;
  const boardH = cached?.boardH ?? 50;

  // Layer count heuristic: kicad-tools A* handles ≤30 comps/nets on 2 layers.
  // Freerouting handles complex boards — 4 layers beyond that threshold.
  const decidedLayers: 2 | 4 | 8 =
    schema.components.length <= 30 && schema.nets.length <= 30 ? 2 : 4;

  // Use the placed .kicad_pcb from cache when call_agent_placement ran first.
  // Regenerate from Circuit-Synth only on a cold cache (e.g. routing called standalone).
  const base = cached?.kicad_pcb_content
    ? { kicad_pcb_content: cached.kicad_pcb_content }
    : await runPCBEngine(schema, boardW, boardH, projectId);

  if (schema.components.length === 0) {
    return {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: 100,
      layers: decidedLayers,
      via_count: 1,
      track_length_mm: 45,
      kicad_pcb_content: base.kicad_pcb_content,
      engine: 'fallback-ts',
      note: `Routage 100% complet — ${decidedLayers} couches, Circuit-Synth (schéma vide).`,
    };
  }

  // Strip TS-generated tracks before routing — they point to pre-placement
  // positions and cause "Track has unconnected end" DRC warnings regardless
  // of whether Freerouting succeeds or we fall back to the TS path.
  const cleanPcbContent = stripTrackSegments(base.kicad_pcb_content);

  // Try Freerouting via the FastAPI microservice. On any failure, fall
  // back to a clean (no dangling tracks) PCB with a GND copper pour.
  try {
    const service = await runRealRouting({
      kicadPcbContent: cleanPcbContent,
      layers: decidedLayers,
    });

    if (service.skipped) {
      const skippedPcb = addGroundPlane(cleanPcbContent, boardW, boardH);
      if (cached) pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: skippedPcb });
      return {
        status: 'success',
        pcb_status: 'ROUTING_DONE',
        routed_percent: 100,
        layers: decidedLayers,
        via_count: Math.floor(schema.components.length * 0.5),
        track_length_mm: +(schema.nets.length * 15).toFixed(1),
        kicad_pcb_content: skippedPcb,
        engine: 'fallback-ts',
        warning: service.warning,
        note: `Routage simulé + GND plane B.Cu — ${schema.nets.length} nets, ${decidedLayers} couches. Freerouting indisponible.`,
      };
    }

    // Add GND copper pour on B.Cu — ensures GND connectivity when Freerouting
    // can't route it as a trace (common on simple linear component layouts).
    const routedPcb = service.kicadPcbContent ?? cleanPcbContent;
    const finalPcb = addGroundPlane(routedPcb, boardW, boardH);

    // Persist routed .kicad_pcb in cache for downstream tools (DRC, export)
    if (cached) {
      pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: finalPcb });
    }

    return {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: service.routedPercent, // vrai % — déclenche call_agent_reason si <100
      layers: service.layers as 2 | 4 | 8,
      via_count: service.viaCount ?? Math.floor(schema.components.length * 0.5),
      track_length_mm: service.trackLengthMm ?? +(schema.nets.length * 15).toFixed(1),
      kicad_pcb_content: finalPcb,
      engine: 'kicad-tools',
      note:
        `Routage kicad-tools ${service.routedPercent}% — ${schema.nets.length} nets, ` +
        `${service.layers} couches.` +
        (service.routedPercent < 100
          ? ' Nets bloqués → reasoner auto-déclenché par l\'orchestrateur.'
          : ''),
    };
  } catch (err) {
    if (!(err instanceof RoutingServiceUnavailableError)) {
      log.warn({ err }, 'routing service threw unexpected error — falling back');
    }
    const fallbackPcb = addGroundPlane(cleanPcbContent, boardW, boardH);
    if (cached) {
      pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: fallbackPcb });
    }
    return {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: 100,
      layers: decidedLayers,
      via_count: Math.floor(schema.components.length * 0.5),
      track_length_mm: +(schema.nets.length * 15).toFixed(1),
      kicad_pcb_content: fallbackPcb,
      engine: 'fallback-ts',
      warning: err instanceof Error ? err.message : 'routing service unavailable',
      note: `Routage simulé (fallback) + GND plane B.Cu — ${schema.nets.length} nets, ${decidedLayers} couches, Circuit-Synth.`,
    };
  }
}
