import { pcbStateCache, log } from '../shared';
import { generateSchemaWithHaiku } from './schema-haiku';
import { validateAndCorrectSchema } from '../../engines/schematic-engine';
import { runCircuitSynthEngine } from '../../engines/engine-router';
import type { SchemaJson } from '../../engines/engine-router';
import { quickLookup } from '../../engines/footprint-service';

/**
 * Schema written OUTSIDE the model, by the driver.
 *
 * `handleSchema` is the ONLY link in the chain that calls a model. Everything
 * after it — ERC, gen_pcb, placement, routing, DRC, export — is deterministic,
 * and the ten-board bench proved it end to end, all the way to Gerbers.
 *
 * So when the Anthropic balance is exhausted (as it has been since 2026-09-06,
 * `400 invalid_request_error`), this is the single seam that unblocks the whole
 * pipeline. The rest of the path below is UNCHANGED: `/schematic/generate`,
 * footprint enrichment, the cache write.
 *
 * ⚠️ This is NOT a simulated mode. The board it leads to is real, measured by a
 * real DRC. What changes is the PROVENANCE, not the quality — which is exactly
 * why `POST /api/jlcpcb/order`, which demands `agent_mode === 'orchestrator'`,
 * still refuses it. Fail closed: unknown provenance is not verified provenance.
 */
function schemaFromDriver(brut: unknown): SchemaJson | null {
  let objet: unknown = brut;
  if (typeof brut === 'string') {
    try {
      objet = JSON.parse(brut);
    } catch {
      return null;
    }
  }
  if (!objet || typeof objet !== 'object' || Array.isArray(objet)) return null;

  // ⚠️ Same rule as the Haiku path, and for the same reason: NEVER fabricate.
  // A schema with no components or no nets cannot produce a board; accepting it
  // would push the failure three steps downstream, where the real cause is
  // invisible — the placement would fail on an empty board and get the blame.
  const o = objet as Record<string, unknown>;
  const components = o['components'];
  const nets = o['nets'];
  if (!Array.isArray(components) || components.length === 0) return null;
  if (!Array.isArray(nets) || nets.length === 0) return null;

  return objet as SchemaJson;
}

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
  let provenance = 'circuit-synth-json';

  // Le driver a-t-il ecrit le schema lui-meme ? Alors aucun modele n est appele.
  const fourni = input['schema_json'];
  if (fourni !== undefined && fourni !== null && fourni !== '') {
    schema = schemaFromDriver(fourni);
    if (!schema) {
      log.error({ projectId }, 'call_agent_schema: schema fourni illisible — aucun repli');
      return {
        status: 'error',
        error: 'Driver schema is unreadable or empty (needs non-empty components and nets).',
        note: 'Schema fourni illisible ou vide — aucun schema fabrique.',
      };
    }
    provenance = 'driver-json';
  } else if (desc) {
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
  // ⚠️ L heuristique PLAFONNE a 50 x 40 mm au-dela de 12 composants, et le banc
  // des dix cartes a mesure que la SURFACE est le levier : `carte-08` passe de
  // 216 connexions manquantes a ZERO en l agrandissant de 110x80 a 125x95, rien
  // d autre n ayant change. Un board de 70 composants sur 50 x 40 mm est hors
  // d atteinte quel que soit le routeur.
  //
  // Le driver peut donc dimensionner la carte. On ne TOUCHE PAS au defaut : le
  // chemin Haiku garde exactement le comportement qu il avait.
  const demande = schema as unknown as Record<string, unknown>;
  const largeur = Number(demande['board_width_mm']);
  const hauteur = Number(demande['board_height_mm']);
  const boardW = Number.isFinite(largeur) && largeur > 0
    ? largeur : (n <= 5 ? 30 : n <= 12 ? 40 : 50);
  const boardH = Number.isFinite(hauteur) && hauteur > 0
    ? hauteur : (n <= 5 ? 25 : n <= 12 ? 35 : 40);

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
    engine: provenance,
    kicad_sch_content: csResult.kicad_sch_content,
    unresolved_footprints: unresolvedFootprints,
    note: `Schéma JSON — ${schema.components.length} composants, ${schema.nets.length} nets.${unresolvedFootprints.length > 0 ? ` ${unresolvedFootprints.length} footprint(s) à résoudre via call_agent_footprint.` : ' Tous les footprints résolus.'}`,
  };
}
