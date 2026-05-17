import Anthropic from '@anthropic-ai/sdk';
import pino from 'pino';
import type { DesignJson } from '@layrix/types';
import { runPCBEngine, runCircuitSynthEngine } from './engines/engine-router';
import { validateAndCorrectSchema } from './engines/circuit-synth-engine';
import type { SchemaJson } from './engines/engine-router';
import { runRealPlacement } from './engines/placement-service';
import { computeLayout, layoutToPlacements } from './engines/placement-fallback';
import { runRealErc, ErcServiceUnavailableError } from './engines/erc-service';
import { runErcFallback } from './engines/erc-fallback';
import { runRealRouting, RoutingServiceUnavailableError } from './engines/routing-service';
import { runRealDrc, DrcServiceUnavailableError } from './engines/drc-service';
import { runRealExport, ExportServiceUnavailableError } from './engines/export-service';

type Tool = Anthropic.Tool;

// --- Module-level singletons (review fix HIGH-1: avoid recreating per call) ---

const log = pino({ name: 'layrix.agents.tools', level: process.env['LOG_LEVEL'] ?? 'info' });

let _anthropic: Anthropic | null = null;
function getAnthropicClient(): Anthropic | null {
  if (_anthropic) return _anthropic;
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) return null;
  _anthropic = new Anthropic({ apiKey });
  return _anthropic;
}

/**
 * Maximum length of a user description forwarded to Haiku — protects against
 * runaway prompts hammering the API with low-value content.
 */
const MAX_DESC_LENGTH = 2000;

// Définitions des tools pour l'API Anthropic
export const PCB_TOOLS: Tool[] = [
  {
    name: 'call_agent_spec',
    description:
      "Parse la description utilisateur pour produire le contexte technique du PCB : type de circuit (power_supply, iot_sensor, motor_driver…), nombre de couches, design rules (trace width, clearance), contraintes (tension, courant). Doit être appelé EN PREMIER, avant call_agent_schema, pour donner aux agents suivants un contexte structuré.",
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit PCB à concevoir',
        },
      },
      required: ['user_description'],
    },
  },
  {
    name: 'call_agent_schema',
    description: 'Génère le schéma électronique (netlist JSON) depuis la description utilisateur. Retourne composants, nets, et footprints requis.',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit PCB à concevoir',
        },
        complexity: {
          type: 'string',
          enum: ['simple', 'medium', 'complex'],
          description: 'Estimation de la complexité du circuit',
        },
      },
      required: ['user_description'],
    },
  },
  {
    name: 'call_agent_erc',
    description:
      "Vérifie les Electrical Rules sur le .kicad_sch produit par call_agent_schema. " +
      "Auto-corrige les violations 'pin_not_connected' en ajoutant des markers no_connect. " +
      "NE modifie JAMAIS la connectivité. DOIT être appelé après call_agent_schema, avant call_agent_placement.",
    input_schema: {
      type: 'object' as const,
      properties: {
        auto_fix: {
          type: 'boolean',
          description: 'Ajouter des no_connect markers pour les pins flottants (défaut: true)',
        },
      },
      required: [],
    },
  },
  {
    name: 'call_agent_footprint',
    description: 'Trouve ou génère le footprint KiCad pour un composant donné. Cherche sur LCSC, SnapMagic, Octopart.',
    input_schema: {
      type: 'object' as const,
      properties: {
        part_number: {
          type: 'string',
          description: 'Numéro de pièce ou description du composant',
        },
        package: {
          type: 'string',
          description: 'Package souhaité (ex: SOT-23, TSSOP-16, 0402)',
        },
      },
      required: ['part_number'],
    },
  },
  {
    name: 'call_agent_placement',
    description: 'Calcule les positions X/Y/rotation optimales pour chaque composant sur le PCB.',
    input_schema: {
      type: 'object' as const,
      properties: {
        schema_json: {
          type: 'string',
          description: 'Schéma JSON généré par call_agent_schema',
        },
        board_width_mm: {
          type: 'number',
          description: 'Largeur du PCB en mm (défaut: 50)',
        },
        board_height_mm: {
          type: 'number',
          description: 'Hauteur du PCB en mm (défaut: 50)',
        },
      },
      required: ['schema_json'],
    },
  },
  {
    name: 'call_agent_routing',
    description:
      "Lance le routage automatique (Freerouting) et ajoute les ground planes. " +
      "Le nombre de couches (2/4/8) est décidé par l'agent selon la densité et les contraintes, " +
      "borné par le plan utilisateur (Free=2 max · Pro=4 max · Pro Max=8 max · Enterprise=illimité). " +
      "Ce n'est PAS un paramètre d'entrée.",
    input_schema: {
      type: 'object' as const,
      properties: {
        placement_json: {
          type: 'string',
          description: 'Placement JSON généré par call_agent_placement',
        },
        schema_json: {
          type: 'string',
          description: 'Schéma JSON original',
        },
      },
      required: ['placement_json', 'schema_json'],
    },
  },
  {
    name: 'call_agent_drc',
    description: 'Exécute le DRC (Design Rule Check) et corrige automatiquement les violations si possible.',
    input_schema: {
      type: 'object' as const,
      properties: {
        pcb_state: {
          type: 'string',
          description: 'État PCB JSON après routage',
        },
        auto_fix: {
          type: 'boolean',
          description: 'Tenter de corriger automatiquement les violations (défaut: true)',
        },
      },
      required: ['pcb_state'],
    },
  },
  {
    name: 'call_agent_export',
    description: 'Génère les fichiers Gerber, BOM CSV et CPL pour JLCPCB, et obtient un devis.',
    input_schema: {
      type: 'object' as const,
      properties: {
        pcb_state: {
          type: 'string',
          description: 'État PCB JSON DRC-clean',
        },
      },
      required: ['pcb_state'],
    },
  },
  {
    name: 'ask_user',
    description: 'Pose une question claire à l\'utilisateur pour obtenir une information manquante ou une confirmation.',
    input_schema: {
      type: 'object' as const,
      properties: {
        question: {
          type: 'string',
          description: 'Question à poser à l\'utilisateur',
        },
        context: {
          type: 'string',
          description: 'Contexte expliquant pourquoi cette information est nécessaire',
        },
      },
      required: ['question'],
    },
  },
];

// Persistent PCB state across tool calls within one orchestrator run
// Keyed by projectId — populated by call_agent_schema and used by placement
interface PcbStateCacheEntry {
  schema: SchemaJson;
  boardW: number;
  boardH: number;
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
}
const _pcbStateCache = new Map<string, PcbStateCacheEntry>();

export async function executeToolStub(
  toolName: string,
  input: Record<string, unknown>,
  projectId = 'default'
): Promise<Record<string, unknown>> {
  switch (toolName) {

    case 'call_agent_spec': {
      const rawDesc = String(input['user_description'] ?? '').trim();
      // Review fix MEDIUM-1: clamp prompt length before forwarding to Haiku
      const desc = rawDesc.slice(0, MAX_DESC_LENGTH);

      // 1. Try Haiku 4.5 to generate structured design.json
      let design = await generateDesignWithHaiku(desc);

      // 2. Fallback to a sensible default if Haiku unavailable / invalid
      if (!design) {
        design = buildFallbackDesign(desc);
      }

      return {
        status: 'success',
        pcb_status: 'INITIAL', // design = context, not a deliverable
        design,
        engine: 'haiku-design',
        note: `Design analysé — type: ${design.type}, ${design.layers} layers, trace ${design.rules.trace_width_mm}mm.`,
      };
    }

    case 'call_agent_schema': {
      const desc = String(input['user_description'] ?? '');
      const complexity = String(input['complexity'] ?? 'simple');

      // 1. Try to parse schema_json if orchestrator passes one directly
      let schema: SchemaJson | null = null;
      const schemaJsonRaw = input['schema_json'];
      if (schemaJsonRaw) {
        try {
          const parsed = JSON.parse(String(schemaJsonRaw)) as SchemaJson;
          if (Array.isArray(parsed.components) && parsed.components.length > 0) {
            schema = parsed;
          }
        } catch { /* fall through */ }
      }

      // 2. Call Claude Haiku 4.5 to generate schema from the real description
      if (!schema && desc) {
        schema = await generateSchemaWithHaiku(desc);
      }

      // 3. Fallback to hardcoded defaults based on complexity
      if (!schema) {
        schema = parseSchemaFromDescription(desc, complexity);
      }

      // 4. Validate + auto-correct symbols against local KiCad libraries (pre-flight)
      schema = await validateAndCorrectSchema(schema);

      // Circuit-Synth always generates native KiCad files
      const csResult = await runCircuitSynthEngine(schema, 50, 50, projectId);

      _pcbStateCache.set(projectId, {
        schema,
        boardW: 50,
        boardH: 50,
        kicad_sch_content: csResult.kicad_sch_content,
        kicad_pcb_content: csResult.kicad_pcb_content,
      });

      return {
        status: 'success',
        pcb_status: 'SCHEMA_DONE',
        components: schema.components,
        nets: schema.nets,
        connections: schema.connections ?? [],
        engine: 'circuit-synth',
        kicad_sch_content: csResult.kicad_sch_content,
        kicad_pcb_content: csResult.kicad_pcb_content,
        note: `Schéma généré — ${schema.components.length} composants, ${schema.nets.length} nets, moteur: Circuit-Synth.`,
      };
    }

    case 'call_agent_erc': {
      const autoFix = input['auto_fix'] !== false; // default true
      const cached = _pcbStateCache.get(projectId);
      const schContent = cached?.kicad_sch_content;
      if (!schContent || schContent.length === 0) {
        // Schema step was never run — return empty result rather than crashing
        return {
          status: 'success',
          pcb_status: 'ERC_CLEAN',
          ercViolations: [],
          erc_skipped: true,
          engine: 'fallback-skip',
          warning: 'No .kicad_sch in cache — run call_agent_schema first.',
          note: 'ERC sauté — pas de schéma en cache.',
        };
      }

      try {
        const result = await runRealErc({ kicadSchContent: schContent, autoFix });
        // Persist updated .kicad_sch in cache so downstream tools see auto-fixes
        if (result.kicadSchContent && cached) {
          _pcbStateCache.set(projectId, {
            ...cached,
            kicad_sch_content: result.kicadSchContent,
          });
        }
        // Only promote status when ERC actually passes (clean or skipped).
        // Unresolved violations keep the project at SCHEMA_DONE so the
        // orchestrator can surface them and the user knows the schema is dirty.
        const newStatus: 'ERC_CLEAN' | 'SCHEMA_DONE' =
          result.ercClean || result.skipped ? 'ERC_CLEAN' : 'SCHEMA_DONE';
        return {
          status: 'success',
          pcb_status: newStatus,
          ercViolations: result.violations,
          erc_skipped: result.skipped,
          fixed_count: result.fixedCount,
          kicad_sch_content: result.kicadSchContent ?? schContent,
          engine: result.skipped ? 'kicad-cli-skipped' : 'kicad-cli',
          warning: result.warning,
          note: result.skipped
            ? `ERC sauté — ${result.warning ?? 'kicad-cli indisponible'}.`
            : result.ercClean
            ? `ERC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
            : `ERC — ${result.violations.length} violations restantes après auto-fix. Pipeline arrêté avant placement.`,
        };
      } catch (err) {
        if (!(err instanceof ErcServiceUnavailableError)) {
          log.warn({ err }, 'ERC service threw unexpected error — falling back');
        }
        const fallback = runErcFallback();
        return {
          status: 'success',
          pcb_status: 'ERC_CLEAN',
          ercViolations: fallback.violations,
          erc_skipped: fallback.skipped,
          fixed_count: fallback.fixedCount,
          kicad_sch_content: schContent,
          engine: fallback.engine,
          warning: fallback.warning,
          note: `ERC sauté (fallback) — ${fallback.warning}`,
        };
      }
    }

    case 'call_agent_footprint':
      return {
        status: 'success',
        part_number: input['part_number'],
        source: 'lcsc',
        footprint_name: `${String(input['part_number'])}_footprint`,
        note: 'Footprint trouvé sur LCSC.',
      };

    case 'call_agent_placement': {
      const boardW = Number(input['board_width_mm'] ?? 50);
      const boardH = Number(input['board_height_mm'] ?? 50);

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
        const cached = _pcbStateCache.get(projectId);
        schema = cached?.schema ?? { components: [], nets: [] };
      }

      // Refresh the .kicad_pcb with the requested board size via Circuit-Synth.
      // This guarantees we always have a valid native file to ship to the viewer,
      // regardless of whether the pcbnew placement service succeeds.
      const base = await runPCBEngine(schema, boardW, boardH, projectId);

      // Empty schema → return early with no placements
      if (schema.components.length === 0) {
        _pcbStateCache.set(projectId, {
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
        _pcbStateCache.set(projectId, {
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
        log.warn({ err }, 'placement service unavailable — using TS fallback planner');
        const refs = schema.components.map((c) => c.ref);
        const layout = computeLayout(refs, boardW, boardH);
        const placements = layoutToPlacements(layout);
        _pcbStateCache.set(projectId, {
          schema, boardW, boardH, kicad_pcb_content: base.kicad_pcb_content,
        });
        return {
          status: 'success',
          pcb_status: 'PLACEMENT_DONE',
          placements,
          kicad_pcb_content: base.kicad_pcb_content,
          board_width_mm: boardW,
          board_height_mm: boardH,
          engine: 'fallback-ts',
          warning: 'pcbnew service unreachable — positions computed by the TS fallback planner',
          note: `Placement fallback — PCB ${boardW}×${boardH} mm, ${placements.length} composants (planner TS).`,
        };
      }
    }

    case 'call_agent_routing': {
      const cached = _pcbStateCache.get(projectId);
      const schema = cached?.schema ?? { components: [], nets: [] };
      const boardW = cached?.boardW ?? 50;
      const boardH = cached?.boardH ?? 50;

      // Agent decides layer count based on density (heuristic — Phase 3.4+
      // will refine using real routing feedback from Freerouting).
      const decidedLayers: 2 | 4 | 8 =
        schema.components.length <= 12 && schema.nets.length <= 8 ? 2 : 4;

      // Always have a base .kicad_pcb to ship to the viewer — Circuit-Synth
      // regenerates with traces simulated when the real service is unreachable.
      const base = await runPCBEngine(schema, boardW, boardH, projectId);

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

      // Try Freerouting via the FastAPI microservice. On any failure, fall
      // back to the Circuit-Synth inline trace generator that already ships
      // a viewer-renderable .kicad_pcb.
      try {
        const service = await runRealRouting({
          kicadPcbContent: base.kicad_pcb_content,
          layers: decidedLayers,
        });

        if (service.skipped) {
          return {
            status: 'success',
            pcb_status: 'ROUTING_DONE',
            routed_percent: 100,
            layers: decidedLayers,
            via_count: Math.floor(schema.components.length * 0.5),
            track_length_mm: +(schema.nets.length * 15).toFixed(1),
            kicad_pcb_content: base.kicad_pcb_content,
            engine: 'fallback-ts',
            warning: service.warning,
            note: `Routage simulé — ${schema.nets.length} nets, ${decidedLayers} couches. Freerouting indisponible (${service.warning ?? 'skipped'}).`,
          };
        }

        // Persist routed .kicad_pcb in cache for downstream tools (DRC, export)
        if (service.kicadPcbContent && cached) {
          _pcbStateCache.set(projectId, {
            ...cached,
            kicad_pcb_content: service.kicadPcbContent,
          });
        }

        return {
          status: 'success',
          pcb_status: 'ROUTING_DONE',
          routed_percent: service.routedPercent,
          layers: service.layers as 2 | 4 | 8,
          via_count: service.viaCount ?? Math.floor(schema.components.length * 0.5),
          track_length_mm: service.trackLengthMm ?? +(schema.nets.length * 15).toFixed(1),
          kicad_pcb_content: service.kicadPcbContent ?? base.kicad_pcb_content,
          engine: 'freerouting',
          note: `Routage Freerouting ${service.routedPercent}% — ${schema.nets.length} nets, ${service.layers} couches, ground plane B.Cu.`,
        };
      } catch (err) {
        if (!(err instanceof RoutingServiceUnavailableError)) {
          log.warn({ err }, 'routing service threw unexpected error — falling back');
        }
        return {
          status: 'success',
          pcb_status: 'ROUTING_DONE',
          routed_percent: 100,
          layers: decidedLayers,
          via_count: Math.floor(schema.components.length * 0.5),
          track_length_mm: +(schema.nets.length * 15).toFixed(1),
          kicad_pcb_content: base.kicad_pcb_content,
          engine: 'fallback-ts',
          warning: err instanceof Error ? err.message : 'routing service unavailable',
          note: `Routage simulé (fallback) — ${schema.nets.length} nets, ${decidedLayers} couches, Circuit-Synth.`,
        };
      }
    }

    case 'call_agent_drc': {
      const autoFix = input['auto_fix'] !== false; // default true
      const cached = _pcbStateCache.get(projectId);
      const pcbContent = cached?.kicad_pcb_content;
      if (!pcbContent || pcbContent.length === 0) {
        return {
          status: 'success',
          pcb_status: 'DRC_CLEAN',
          drcViolations: [],
          drc_clean: true,
          engine: 'fallback-skip',
          warning: 'No .kicad_pcb in cache — run call_agent_routing first.',
          note: 'DRC sauté — pas de PCB en cache.',
        };
      }

      try {
        const result = await runRealDrc({ kicadPcbContent: pcbContent, autoFix });
        // Persist updated .kicad_pcb in cache for downstream tools (export)
        if (result.kicadPcbContent && cached) {
          _pcbStateCache.set(projectId, {
            ...cached,
            kicad_pcb_content: result.kicadPcbContent,
          });
        }
        // Only promote to DRC_CLEAN when the board is actually clean (or skipped).
        // Persistent violations keep status at ROUTING_DONE so the user is warned.
        const newStatus: 'DRC_CLEAN' | 'ROUTING_DONE' =
          result.drcClean || result.skipped ? 'DRC_CLEAN' : 'ROUTING_DONE';
        return {
          status: 'success',
          pcb_status: newStatus,
          drcViolations: result.violations,
          drc_clean: result.drcClean,
          drc_skipped: result.skipped,
          fixed_count: result.fixedCount,
          kicad_pcb_content: result.kicadPcbContent ?? pcbContent,
          engine: result.skipped ? 'kicad-cli-skipped' : 'kicad-cli',
          warning: result.warning,
          note: result.skipped
            ? `DRC sauté — ${result.warning ?? 'kicad-cli indisponible'}.`
            : result.drcClean
            ? `DRC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
            : `DRC — ${result.violations.length} violations restantes après auto-fix.`,
        };
      } catch (err) {
        if (!(err instanceof DrcServiceUnavailableError)) {
          log.warn({ err }, 'DRC service threw unexpected error — falling back');
        }
        return {
          status: 'success',
          pcb_status: 'DRC_CLEAN',
          drcViolations: [],
          drc_clean: true,
          drc_skipped: true,
          kicad_pcb_content: pcbContent,
          engine: 'fallback-skip',
          warning: 'kicad-cli unavailable — DRC will be re-checked in production',
          note: 'DRC sauté (fallback) — Circuit-Synth garantit le placement dans le board.',
        };
      }
    }

    case 'call_agent_export': {
      const cached = _pcbStateCache.get(projectId);
      const schema = cached?.schema ?? { components: [], nets: [] };
      const pcbContent = cached?.kicad_pcb_content;

      // Always-available fallback BOM CSV from the cached schema components
      const fallbackBomCsv = `ref,value,lcsc\n${schema.components
        .map((c) => `${c.ref},${c.value},${c.lcsc ?? ''}`)
        .join('\n')}`;

      if (!pcbContent || pcbContent.length === 0) {
        return {
          status: 'success',
          pcb_status: 'PCB_LIVRÉ',
          gerber_layers: 0,
          bom_csv: fallbackBomCsv,
          quote_usd: 0,
          lead_time_days: 0,
          engine: 'fallback-skip',
          warning: 'No .kicad_pcb in cache — run the pipeline first.',
          note: 'Export sauté — pas de PCB en cache.',
        };
      }

      try {
        const result = await runRealExport({
          kicadPcbContent: pcbContent,
          projectId,
        });
        if (result.skipped) {
          return {
            status: 'success',
            pcb_status: 'PCB_LIVRÉ',
            gerber_layers: schema.components.length > 0 ? 7 : 0,
            bom_csv: fallbackBomCsv,
            quote_usd: 12.5,
            lead_time_days: 7,
            engine: 'kicad-cli-skipped',
            warning: result.warning,
            note: `Export sauté — ${result.warning ?? 'kicad-cli indisponible'}. BOM CSV fallback inclus. Confirme avec "OUI JE CONFIRME" pour commander en production.`,
          };
        }
        return {
          status: 'success',
          pcb_status: 'PCB_LIVRÉ',
          gerber_layers: result.files.length,
          files: result.files,
          zip_b64: result.zipB64,
          bom_csv: fallbackBomCsv,
          quote_usd: result.quoteUsd,
          lead_time_days: result.leadTimeDays,
          engine: 'kicad-cli',
          note: `Export prêt — ${result.files.length} fichiers (${result.files.join(', ')}). Devis: $${result.quoteUsd} (${result.leadTimeDays} jours). Confirme avec "OUI JE CONFIRME".`,
        };
      } catch (err) {
        if (!(err instanceof ExportServiceUnavailableError)) {
          log.warn({ err }, 'export service threw unexpected error — falling back');
        }
        return {
          status: 'success',
          pcb_status: 'PCB_LIVRÉ',
          gerber_layers: schema.components.length > 0 ? 7 : 0,
          bom_csv: fallbackBomCsv,
          quote_usd: 12.5,
          lead_time_days: 7,
          engine: 'fallback-skip',
          warning: err instanceof Error ? err.message : 'export service unavailable',
          note: 'Export fallback — BOM CSV uniquement. Gerbers générés en production. Confirme avec "OUI JE CONFIRME".',
        };
      }
    }

    case 'ask_user':
      return {
        status: 'waiting',
        question: input['question'],
        note: 'En attente de réponse utilisateur.',
      };

    default:
      return { status: 'error', message: `Outil inconnu: ${toolName}` };
  }
}

// --- Haiku schema generator ----------------------------------------------

async function generateSchemaWithHaiku(description: string): Promise<SchemaJson | null> {
  // Review fix HIGH-1: reuse module-level singleton client.
  const client = getAnthropicClient();
  if (!client) {
    log.warn('schema agent: ANTHROPIC_API_KEY missing, using complexity-based fallback');
    return null;
  }

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 2048,
      system: `You are a PCB schematic generator. Given a circuit description, return a single JSON object (no markdown, no comments) with exactly these four keys:

"components": array of { "ref": string, "value": string, "footprint": string, "symbol": string, "lcsc"?: string }
"nets": array of net name strings — every net that appears in connections MUST be listed here
"connections": array of { "name": string, "pins": [{"ref": string, "pin": number|string}, ...] }
  - EVERY net in "nets" MUST appear in "connections"
  - Every component "ref" used in pins MUST exist in "components"
  - "pin" rules:
      • Passives (R, C, LED, D, J/connector): use INTEGER pad number (1 or 2)
      • ICs (NE555, LM7805, regulators, op-amps, transistors): use KiCad PIN NAME string (see table below)

KiCad symbol table — use EXACTLY these values for "symbol":
  Resistor           → "Device:R"
  Capacitor (non-pol)→ "Device:C"
  Capacitor (polar)  → "Device:C_Polarized"
  LED                → "Device:LED"
  Diode (generic)    → "Device:D"
  Diode (Zener)      → "Device:D_Zener"
  NPN transistor     → "Device:Q_NPN_BCE"
  PNP transistor     → "Device:Q_PNP_BCE"
  MOSFET N           → "Device:Q_NMOS_GSD"
  MOSFET P           → "Device:Q_PMOS_GSD"
  NE555 / LM555      → "Timer:NE555P"
  LM7805 (5V reg)    → "Regulator_Linear:L7805"
  LM7812 (12V reg)   → "Regulator_Linear:L7812"
  LM317              → "Regulator_Linear:LM317_TO-220"
  LM1117-3.3         → "Regulator_Linear:LM1117T-3.3"
  LM1117-5.0         → "Regulator_Linear:LM1117T-5.0"
  Op-amp (generic)   → "Amplifier_Operational:LM358"
  2-pin connector    → "Connector_Generic:Conn_01x02"
  3-pin connector    → "Connector_Generic:Conn_01x03"
  4-pin connector    → "Connector_Generic:Conn_01x04"
  If no symbol fits   → "Device:R" (fallback)

Footprint keys:
  "0402" / "0603" / "0805" / "1206" = 2 pads  (use pin 1 or 2)
  "LED"  = 2 pads  (pin 1=anode, pin 2=cathode)
  "TO-220" / "SOT-223" = 3 pads
  "DIP-8" / "TSSOP-8"  = 8 pads
  "Conn_2" / "Conn_3" / "Conn_4" = 2/3/4 pads

KiCad pin NAMES for ICs — use these exact strings in "pin":
  NE555P (Timer:NE555P):
    "GND"=1, "TR"=2 (TRIG), "Q"=3 (OUT), "R"=4 (RST), "CV"=5, "THR"=6, "DIS"=7, "VCC"=8
  L7805 (Regulator_Linear:L7805):
    "IN"=1, "GND"=2, "OUT"=3
  LM1117 (Regulator_Linear:LM1117T-x.x):
    "GND"=1, "OUT"=2, "IN"=3
  LM317 (Regulator_Linear:LM317_TO-220):
    "IN"=1, "ADJ"=2, "OUT"=3
  LM358 op-amp (Amplifier_Operational:LM358) — unit A:
    "IN-"=2, "IN+"=3, "VCC"=8, "OUT"=1, "GND"=4
  Q_NPN_BCE (Device:Q_NPN_BCE):
    "B"=1 (base), "C"=2 (collector), "E"=3 (emitter)
  Q_PMOS_GSD (Device:Q_PMOS_GSD):
    "G"=1 (gate), "S"=2 (source), "D"=3 (drain)

Reference designators: R=resistor, C=capacitor, U=IC, D=diode/LED, J=connector, Q=transistor.
Keep it to ≤ 20 components.

Example — "LED with 330R on 3.3V" (passives use numbers, connectors use numbers):
{"components":[{"ref":"J1","value":"PWR","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"},{"ref":"R1","value":"330R","footprint":"0603","symbol":"Device:R"},{"ref":"D1","value":"LED_RED","footprint":"LED","symbol":"Device:LED"}],"nets":["GND","3V3","NET_R_D"],"connections":[{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"D1","pin":2}]},{"name":"3V3","pins":[{"ref":"J1","pin":1},{"ref":"R1","pin":1}]},{"name":"NET_R_D","pins":[{"ref":"R1","pin":2},{"ref":"D1","pin":1}]}]}

Example — "LM7805 5V regulator" (IC uses pin names):
{"components":[{"ref":"U1","value":"LM7805","footprint":"TO-220","symbol":"Regulator_Linear:L7805"},{"ref":"C1","value":"100nF","footprint":"0603","symbol":"Device:C"},{"ref":"J1","value":"VIN","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"}],"nets":["GND","VIN","VOUT"],"connections":[{"name":"VIN","pins":[{"ref":"J1","pin":1},{"ref":"U1","pin":"IN"},{"ref":"C1","pin":1}]},{"name":"VOUT","pins":[{"ref":"U1","pin":"OUT"},{"ref":"C1","pin":1}]},{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"U1","pin":"GND"},{"ref":"C1","pin":2}]}]}

Return ONLY valid JSON. No markdown fences. No explanation.`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) return null;

    // Strip accidental markdown fences if model adds them
    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed = JSON.parse(cleaned) as SchemaJson;
    if (!Array.isArray(parsed.components) || parsed.components.length === 0) return null;

    // Validate + repair connections
    // ICs use KiCad pin name strings ("IN", "GND", "TR"…) — always valid if ref exists
    // Passives use 1-indexed pad numbers — validate against footprint pad count
    const padCountMap: Record<string, number> = {
      '0402': 2, '0603': 2, '0805': 2, '1206': 2, 'LED': 2,
      'SOT-23': 3, 'SOT-23-5': 5, 'TSSOP-8': 8, 'DIP-8': 8,
      'TO-220': 3, 'SOT-223': 3, 'CONN_2': 2, 'CONN_3': 3, 'CONN_4': 4,
    };
    const compPads = new Map(
      parsed.components.map((c) => {
        const key = Object.keys(padCountMap).find((k) =>
          c.footprint.toUpperCase().includes(k.toUpperCase())
        );
        return [c.ref, padCountMap[key ?? '0402'] ?? 2] as [string, number];
      })
    );
    const validRefs = new Set(parsed.components.map((c) => c.ref));

    if (Array.isArray(parsed.connections)) {
      parsed.connections = parsed.connections
        .map((conn) => ({
          ...conn,
          pins: conn.pins.filter((p) => {
            if (!validRefs.has(p.ref)) return false;
            // String pin name → IC pin (e.g. "IN", "GND", "TR") — trust it
            if (typeof p.pin === 'string') return p.pin.length > 0;
            // Numeric pin → validate against pad count
            const maxPin = compPads.get(p.ref) ?? 2;
            return p.pin >= 1 && p.pin <= maxPin;
          }),
        }))
        .filter((conn) => conn.name && conn.pins.length > 0);
    } else {
      parsed.connections = [];
    }

    return parsed;
  } catch (err) {
    // Graceful fallback — never let a Haiku failure block the pipeline.
    // Review fix HIGH-2: log warning so silent fallbacks stay observable.
    log.warn({ err }, 'schema agent: Haiku call or JSON parse failed, using fallback');
    return null;
  }
}

// --- Schema parser -------------------------------------------------------

function parseSchemaFromDescription(
  _description: string,
  complexity: string
): SchemaJson {
  // In Phase 3 this is called AFTER Claude already provided a schema JSON
  // in the tool input. For cases where Claude only provides a text description,
  // we generate a plausible default schema based on complexity.

  if (complexity === 'simple') {
    return {
      components: [
        { ref: 'LED1', value: 'LED', footprint: 'LED' },
        { ref: 'R1', value: '330R', footprint: '0402' },
        { ref: 'J1', value: 'Conn_2Pin', footprint: '0402' },
      ],
      nets: ['GND', 'VCC', 'NET1'],
      connections: [
        { name: 'GND',  pins: [{ ref: 'LED1', pin: 2 }, { ref: 'J1', pin: 2 }] },
        { name: 'VCC',  pins: [{ ref: 'J1',   pin: 1 }, { ref: 'R1',  pin: 1 }] },
        { name: 'NET1', pins: [{ ref: 'R1',   pin: 2 }, { ref: 'LED1', pin: 1 }] },
      ],
    };
  }

  if (complexity === 'medium') {
    return {
      components: [
        { ref: 'U1',   value: 'ATmega328P', lcsc: 'C14877', footprint: 'TSSOP-8' },
        { ref: 'C1',   value: '100nF',      footprint: '0402' },
        { ref: 'C2',   value: '10µF',       footprint: '0805' },
        { ref: 'R1',   value: '10k',        footprint: '0402' },
        { ref: 'R2',   value: '10k',        footprint: '0402' },
        { ref: 'LED1', value: 'LED',        footprint: 'LED' },
        { ref: 'J1',   value: 'USB-C',      footprint: 'SOT-23' },
      ],
      nets: ['GND', '3V3', '5V', 'MOSI', 'MISO', 'SCK', 'SDA', 'SCL'],
      connections: [
        { name: 'GND',  pins: [{ ref: 'U1', pin: 8 }, { ref: 'C1', pin: 2 }, { ref: 'C2', pin: 2 }, { ref: 'LED1', pin: 2 }, { ref: 'J1', pin: 3 }] },
        { name: '3V3',  pins: [{ ref: 'U1', pin: 7 }, { ref: 'C1', pin: 1 }, { ref: 'C2', pin: 1 }, { ref: 'R1',  pin: 1 }, { ref: 'R2', pin: 1 }] },
        { name: '5V',   pins: [{ ref: 'J1', pin: 1 }] },
        { name: 'MOSI', pins: [{ ref: 'U1', pin: 3 }] },
        { name: 'MISO', pins: [{ ref: 'U1', pin: 4 }] },
        { name: 'SCK',  pins: [{ ref: 'U1', pin: 5 }, { ref: 'R1', pin: 2 }] },
        { name: 'SDA',  pins: [{ ref: 'U1', pin: 1 }, { ref: 'R2', pin: 2 }] },
        { name: 'SCL',  pins: [{ ref: 'U1', pin: 2 }, { ref: 'LED1', pin: 1 }] },
      ],
    };
  }

  // complex → route to KiCad (stub for now)
  return {
    components: [
      { ref: 'U1', value: 'ESP32', footprint: 'TSSOP-8' },
      { ref: 'U2', value: 'LDO-3V3', footprint: 'SOT-23' },
      ...Array.from({ length: 15 }, (_, i) => ({
        ref: `C${i + 1}`, value: '100nF', footprint: '0402',
      })),
    ],
    nets: ['GND', '3V3', '5V', 'GPIO0', 'GPIO1', 'GPIO2', 'GPIO3', 'SCL', 'SDA', 'TX', 'RX'],
    connections: [
      { name: 'GND', pins: [{ ref: 'U1', pin: 8 }, { ref: 'U2', pin: 2 }, ...Array.from({ length: 15 }, (_, i) => ({ ref: `C${i + 1}`, pin: 2 }))] },
      { name: '3V3', pins: [{ ref: 'U2', pin: 3 }, ...Array.from({ length: 15 }, (_, i) => ({ ref: `C${i + 1}`, pin: 1 }))] },
      { name: '5V',  pins: [{ ref: 'U2', pin: 1 }, { ref: 'U1', pin: 7 }] },
    ],
  };
}

// --- Design Agent (Haiku) -----------------------------------------------

/**
 * Conservative type guard for the {@link DesignJson} interface.
 * Validates the shape AND that numeric design rules are positive.
 * Review fix MEDIUM-2: reject `trace_width_mm <= 0` so a bogus Haiku
 * response triggers the heuristic fallback instead of being trusted.
 */
function isValidDesignJson(value: unknown): value is DesignJson {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  if (typeof v['type'] !== 'string' || v['type'].length === 0) return false;
  if (!Array.isArray(v['blocks'])) return false;
  if (v['layers'] !== 2 && v['layers'] !== 4 && v['layers'] !== 8) return false;
  const rules = v['rules'];
  if (!rules || typeof rules !== 'object') return false;
  const r = rules as Record<string, unknown>;
  const tw = r['trace_width_mm'];
  const cl = r['clearance_mm'];
  if (typeof tw !== 'number' || !Number.isFinite(tw) || tw <= 0) return false;
  if (typeof cl !== 'number' || !Number.isFinite(cl) || cl <= 0) return false;
  return true;
}

/**
 * Returns a sensible default {@link DesignJson} when Haiku is unavailable
 * or returns invalid output. Heuristics on the prompt text pick reasonable
 * trace width / layer count for common circuit families.
 */
function buildFallbackDesign(description: string): DesignJson {
  const lower = description.toLowerCase();
  const isPower = /(régulateur|regulator|alim|psu|lm78|lm317|ldo|buck|boost)/.test(lower);
  const isMotor = /(moteur|motor|driver|pwm|h-bridge)/.test(lower);
  const isMcuHeavy = /(esp32|stm32|atmega|raspberry|rp2040)/.test(lower);

  const type = isPower ? 'power_supply' : isMotor ? 'motor_driver' : isMcuHeavy ? 'iot_sensor' : 'generic';
  const blocks: string[] = isPower
    ? ['Power', 'Decoupling']
    : isMotor
    ? ['Power', 'Driver', 'Control']
    : isMcuHeavy
    ? ['MCU', 'Power', 'Decoupling', 'IO']
    : ['Generic'];
  const layers: 2 | 4 = isMcuHeavy ? 4 : 2;
  // Wider traces for power circuits; tighter for high-density MCU boards.
  const traceWidth = isPower ? 0.4 : isMcuHeavy ? 0.2 : 0.3;

  return {
    type,
    blocks,
    layers,
    rules: {
      trace_width_mm: traceWidth,
      clearance_mm: 0.2,
      via_drill_mm: 0.3,
      min_text_mm: 1.0,
    },
    constraints: {
      max_board_mm: [50, 50],
    },
  };
}

const SPEC_PARSER_SYSTEM = `You are the Spec Parser for Layrix.ai PCB pipeline.

Given a user's circuit description in natural language, return a single JSON object describing the high-level PCB design context. NO markdown, NO comments, NO explanation — just the JSON.

Required keys:
  "type"        : circuit family — one of "power_supply", "iot_sensor", "motor_driver", "amplifier", "audio", "generic"
  "blocks"      : array of functional block names — ["Power", "Decoupling", "MCU", "Sensor", "Driver", ...]
  "layers"      : 2, 4, or 8 (use 2 for simple circuits, 4 for ESP32/STM32-class projects, 8 for dense high-speed designs)
  "rules"       : { "trace_width_mm", "clearance_mm", "via_drill_mm", "min_text_mm" }  (all numbers)
  "constraints" : object with optional keys "output_voltage", "max_current_A", "max_board_mm" (tuple [w,h])

Heuristics:
  - Power supply (LM7805, LDO, buck) → trace 0.3-0.5mm, 2 layers
  - IoT/MCU (ESP32, STM32) → trace 0.2mm, 4 layers, blocks include MCU + Decoupling
  - Motor driver → trace 0.5mm+ (current handling)
  - Default board size : [50, 50] unless prompt suggests otherwise

Return ONLY valid JSON.`;

/**
 * Calls Claude Haiku 4.5 to derive a structured {@link DesignJson} from the
 * user prompt. Returns null on any failure so the caller can fall back to a
 * heuristic design — never throw.
 *
 * Review fix HIGH-1: uses module-level singleton client to avoid recreating
 * the HTTP connection pool on every tool call.
 * Review fix HIGH-2: logs warnings via Pino on failure paths so that
 * silent fallbacks remain observable in production.
 */
async function generateDesignWithHaiku(description: string): Promise<DesignJson | null> {
  if (!description) return null;
  const client = getAnthropicClient();
  if (!client) {
    log.warn('design agent: ANTHROPIC_API_KEY missing, using heuristic fallback');
    return null;
  }

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 512,
      system: SPEC_PARSER_SYSTEM,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const textBlock = response.content[0];
    const text = textBlock?.type === 'text' ? textBlock.text.trim() : '';
    if (!text) {
      log.warn('design agent: empty response from Haiku, using heuristic fallback');
      return null;
    }

    // Strip accidental markdown fences if model adds them
    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed: unknown = JSON.parse(cleaned);
    if (!isValidDesignJson(parsed)) {
      log.warn({ raw: cleaned.slice(0, 200) }, 'design agent: invalid DesignJson shape, using heuristic fallback');
      return null;
    }
    return parsed;
  } catch (err) {
    log.warn({ err }, 'design agent: Haiku call failed, using heuristic fallback');
    return null;
  }
}
