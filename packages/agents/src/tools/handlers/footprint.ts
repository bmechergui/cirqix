import { pcbStateCache, log } from '../shared';
import { findFootprint } from '../../engines/footprint-service';

export async function handleFootprint(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const pn = String(input['part_number'] ?? '').trim();
  const ref = String(input['component_ref'] ?? '').trim();
  const pkg = input['package'] ? String(input['package']).trim() : undefined;
  if (!pn) {
    return { status: 'error', note: 'part_number requis.' };
  }
  try {
    const result = await findFootprint(pn, pkg);

    // Met à jour le cache avec le footprint résolu — call_agent_gen_pcb l'utilisera
    if (ref) {
      const cached = pcbStateCache.get(projectId);
      if (cached?.schema.components) {
        const updatedComponents = cached.schema.components.map((c) =>
          c.ref === ref ? { ...c, footprint: result.footprint_name } : c
        );
        pcbStateCache.set(projectId, {
          ...cached,
          schema: { ...cached.schema, components: updatedComponents },
        });
      }
    }

    return {
      status: 'success',
      component_ref: ref || null,
      part_number: pn,
      footprint_name: result.footprint_name,
      source: result.source,
      kicad_mod: result.kicad_mod ?? null,
      lcsc: result.lcsc ?? null,
      package_type: result.package_type ?? null,
      note: result.note,
    };
  } catch (err) {
    const msg = err instanceof Error ? err.message : 'Footprint resolution failed';
    log.error({ err, pn }, 'call_agent_footprint error');
    return { status: 'error', part_number: pn, note: msg };
  }
}
