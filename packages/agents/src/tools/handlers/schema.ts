import { pcbStateCache, log } from '../shared';
import { generateSchemaWithHaiku, generateSchematicCodeWithHaiku } from './schema-haiku';
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
  const serviceUrl = process.env.KICAD_SERVICE_URL;

  // ── Path A: circuit_synth Python code → Docker /schematic/execute ────
  // Haiku génère Python avec symboles KiCad natifs + stratégie connecteur.
  // Docker exécute → .kicad_sch natif multi-pins (62KB+ pour ESP32).
  // Sortie : .kicad_sch UNIQUEMENT — le PCB est généré par call_agent_gen_pcb.
  if (serviceUrl && desc) {
    try {
      const codeResult = await generateSchematicCodeWithHaiku(desc);
      if (codeResult?.code) {
        const n = codeResult.footprints.length || 6;
        const boardW = n <= 5 ? 30 : n <= 12 ? 40 : 50;
        const boardH = n <= 5 ? 25 : n <= 12 ? 35 : 40;

        const execRes = await fetch(`${serviceUrl}/schematic/execute`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            code: codeResult.code,
            project_id: projectId,
            board_width_mm: boardW,
            board_height_mm: boardH,
          }),
          signal: AbortSignal.timeout(60_000),
        });

        if (execRes.ok) {
          const execData = await execRes.json() as {
            success: boolean;
            kicad_sch_content?: string | null;
            kicad_pcb_content?: string | null;
            error?: string;
          };

          if (!execData.success) {
            log.warn({ error: execData.error, projectId }, 'Path A: Docker execute returned success=false');
          }

          if (execData.success && execData.kicad_sch_content) {
            const enrichedComponents = codeResult.footprints.map((c) => ({
              ...c,
              footprint: quickLookup(c.ref, c.footprint) ?? c.footprint,
            }));
            const unresolvedFootprints = enrichedComponents
              .filter((c) => !c.footprint.includes(':'))
              .map((c) => ({ ref: c.ref, value: c.value, footprint: c.footprint }));

            const schema: SchemaJson = {
              components: enrichedComponents,
              nets: codeResult.footprints.map((_, i) => `NET_${i}`),
              connections: [],
            };

            pcbStateCache.set(projectId, {
              schema,
              boardW,
              boardH,
              kicad_sch_content: execData.kicad_sch_content,
              // kicad_pcb_content intentionnellement absent — call_agent_gen_pcb le génère
            });

            return {
              status: 'success',
              pcb_status: 'SCHEMA_DONE',
              components: enrichedComponents,
              nets: schema.nets,
              connections: [],
              engine: 'circuit-synth-execute',
              kicad_sch_content: execData.kicad_sch_content,
              unresolved_footprints: unresolvedFootprints,
              note: `Schéma circuit_synth — ${enrichedComponents.length} composants, symboles KiCad natifs.${unresolvedFootprints.length > 0 ? ` ${unresolvedFootprints.length} footprint(s) à résoudre via call_agent_footprint.` : ''}`,
            };
          }
        }
      }
    } catch (err) {
      log.warn({ err, projectId }, 'Path A: circuit_synth execute failed — falling back to JSON schema');
    }
  } else {
    log.warn({ serviceUrl: !!serviceUrl, desc: !!desc }, 'Path A: skipped — missing serviceUrl or desc');
  }

  // ── Path B: JSON schema via Haiku (fallback) ──────────────────────────
  // Haiku génère JSON schema avec stratégie connecteur pour MCUs complexes.
  let schema: SchemaJson | null = null;

  if (desc) {
    schema = await generateSchemaWithHaiku(desc);
  }

  if (!schema) {
    // Path A (circuit_synth Python) and Path B (Haiku JSON) both failed.
    // NEVER fabricate a hardcoded schema unrelated to the user's request —
    // an ATmega328P for a temperature sensor, or a generic LED board for a
    // voltage divider, looks like success but is wrong, so the user wastes
    // credits re-iterating. Surface a real, diagnostic error instead so the
    // actual cause (Docker down, missing API key, truncated JSON) is fixed.
    const hasApiKey = !!process.env['ANTHROPIC_API_KEY'];
    const pathA = serviceUrl ? 'failed or unreachable' : 'KICAD_SERVICE_URL not set';
    const pathB = hasApiKey ? 'invalid or truncated Haiku response' : 'ANTHROPIC_API_KEY not set';
    log.error(
      { projectId, complexity, hasApiKey, hasServiceUrl: !!serviceUrl },
      'call_agent_schema: all schema paths failed — no fabricated fallback'
    );
    return {
      status: 'error',
      error: `Schema generation failed — Path A (circuit_synth/Docker): ${pathA}; Path B (Haiku JSON): ${pathB}. Fix the cause and retry, or refine the description.`,
      note: 'Génération du schéma échouée — aucun schéma fabriqué (les deux moteurs IA sont indisponibles). Corrige la cause puis relance.',
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
