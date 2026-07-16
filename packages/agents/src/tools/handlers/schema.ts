import { pcbStateCache, log } from '../shared';
import { generateSchemaWithHaiku } from './schema-haiku';
import { validateAndCorrectSchema } from '../../engines/schematic-engine';
import { runCircuitSynthEngine } from '../../engines/engine-router';
import type { SchemaJson } from '../../engines/engine-router';
import { quickLookup } from '../../engines/footprint-service';

export async function handleSchema(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const desc = String(input['user_description'] ?? '');
  const complexity = String(input['complexity'] ?? 'simple');

  // JSON schema via Haiku. Generated Python is never executed by the shared
  // KiCad service; the typed schema is rendered through /schematic/generate.
  // Haiku génère JSON schema avec stratégie connecteur pour MCUs complexes.
  let schema: SchemaJson | null = null;

  if (desc) {
    schema = await generateSchemaWithHaiku(desc);
  }

  if (!schema) {
    // NEVER fabricate a hardcoded schema unrelated to the user's request —
    // an ATmega328P for a temperature sensor, or a generic LED board for a
    // voltage divider, looks like success but is wrong, so the user wastes
    // credits re-iterating. Surface a real, diagnostic error instead so the
    // actual cause (Docker down, missing API key, truncated JSON) is fixed.
    const hasApiKey = !!process.env['ANTHROPIC_API_KEY'];
    const cause = hasApiKey ? 'invalid or truncated Haiku response' : 'ANTHROPIC_API_KEY not set';
    log.error(
      { projectId, complexity, hasApiKey },
      'call_agent_schema: schema generation failed — no fabricated fallback'
    );
    return {
      status: 'error',
      error: `Schema generation failed — Haiku JSON: ${cause}. Fix the cause and retry, or refine the description.`,
      note: 'Génération du schéma échouée — aucun schéma fabriqué. Corrige la cause puis relance.',
    };
  }

  schema = await validateAndCorrectSchema(schema);

  const n = schema.components.length;
  const boardW = n <= 5 ? 30 : n <= 12 ? 40 : 50;
  const boardH = n <= 5 ? 25 : n <= 12 ? 35 : 40;

  // Path B génère le .kicad_sch via /schematic/generate (Docker) ou TS inline
  const csResult = await runCircuitSynthEngine(schema, boardW, boardH, projectId);

  const enrichedComponents = schema.components.map((c) => ({
    ...c,
    footprint: quickLookup(c.ref, c.footprint) ?? c.footprint,
  }));
  const unresolvedFootprints = enrichedComponents
    .filter((c) => !c.footprint.includes(':'))
    .map((c) => ({ ref: c.ref, value: c.value, footprint: c.footprint }));

  const enrichedSchema = { ...schema, components: enrichedComponents };

  pcbStateCache.set(projectId, {
    schema: enrichedSchema,
    boardW,
    boardH,
    kicad_sch_content: csResult.kicad_sch_content,
    // kicad_pcb_content intentionnellement absent — call_agent_gen_pcb le génère
  });

  return {
    status: 'success',
    pcb_status: 'SCHEMA_DONE',
    components: enrichedComponents,
    nets: schema.nets,
    connections: schema.connections ?? [],
    engine: 'circuit-synth-json',
    kicad_sch_content: csResult.kicad_sch_content,
    unresolved_footprints: unresolvedFootprints,
    note: `Schéma JSON — ${schema.components.length} composants, ${schema.nets.length} nets.${unresolvedFootprints.length > 0 ? ` ${unresolvedFootprints.length} footprint(s) à résoudre via call_agent_footprint.` : ' Tous les footprints résolus.'}`,
  };
}
