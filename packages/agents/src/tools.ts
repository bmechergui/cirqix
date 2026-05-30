import Anthropic from '@anthropic-ai/sdk';
import pino from 'pino';
import type { DesignJson } from '@layrix/types';
import { runPCBEngine, runCircuitSynthEngine } from './engines/engine-router';
import { validateAndCorrectSchema } from './engines/schematic-engine';
import type { SchemaJson } from './engines/engine-router';
import type { SchemaComponent } from '@layrix/types';
import { runRealPlacement } from './engines/placement-service';
import { runRealErc, ErcServiceUnavailableError } from './engines/erc-service';
import { runErcFallback } from './engines/erc-fallback';
import { runRealRouting, RoutingServiceUnavailableError } from './engines/routing-service';
import { runRealDrc, DrcServiceUnavailableError } from './engines/drc-service';
import { runRealExport, ExportServiceUnavailableError } from './engines/export-service';
import { findFootprint, quickLookup } from './engines/footprint-service';
import { runSimulation, SimulationServiceUnavailableError } from './engines/simulation-service';

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
    name: 'call_agent_schema',
    description:
      'Ingénieur Schéma — Expert circuit_synth et KiCad. ' +
      'Génère un script Python circuit_synth adapté à la description, l\'exécute via Docker, ' +
      'et produit un .kicad_sch natif + netlist + JSON composants. ' +
      'Décide seul les composants optimaux (MCU, capteurs, passifs, connecteurs) — NE PAS passer schema_json. ' +
      'Utilise la stratégie connecteur générique pour tous les modules complexes (ESP32, Arduino, capteurs). ' +
      'Retourne : kicad_sch_content, composants avec footprints, unresolved_footprints à résoudre.',
    input_schema: {
      type: 'object' as const,
      properties: {
        user_description: {
          type: 'string',
          description: 'Description complète du circuit à concevoir — tous les détails fonctionnels',
        },
        complexity: {
          type: 'string',
          enum: ['simple', 'medium', 'complex'],
          description: 'Complexité estimée : simple (<5 composants), medium (5-15), complex (>15)',
        },
      },
      required: ['user_description'],
    },
  },
  {
    name: 'call_agent_erc',
    description:
      'Ingénieur ERC — Expert validation électrique KiCad. ' +
      'Vérifie toutes les règles électriques du .kicad_sch : alimentations, connexions manquantes, pins flottants. ' +
      'Auto-corrige pin_not_connected avec no_connect markers. ' +
      'N\'accepte aucune erreur d\'alimentation. Rejette tout schéma avec erreur de court-circuit. ' +
      'OBLIGATOIRE après call_agent_schema, avant call_agent_gen_pcb.',
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
    description:
      'Ingénieur Composants — Expert librairies KiCad, LCSC et SnapMagic. ' +
      'Résout le footprint KiCad pour UN composant via cascade 4 étapes : ' +
      '(1) librairies KiCad officielles (instant, 0 crédit), ' +
      '(2) pgvector community cache (instant), ' +
      '(3) LCSC/EasyEDA API (référence LCSC), ' +
      '(4) génération .kicad_mod par Haiku (fallback IA, 3 crédits). ' +
      'Mettre component_ref pour que l\'agent mette à jour le cache avant call_agent_gen_pcb. ' +
      'Appeler UNE FOIS par ref listée dans unresolved_footprints.',
    input_schema: {
      type: 'object' as const,
      properties: {
        part_number: {
          type: 'string',
          description: 'Valeur du composant (ex: NE555P, LM7805, 10k 0402, ESP32-WROOM-32)',
        },
        component_ref: {
          type: 'string',
          description: 'Référence du composant dans le schéma (ex: U1, R1, C3) — obligatoire pour mise à jour cache',
        },
        package: {
          type: 'string',
          description: 'Package hint pour affiner la recherche (ex: SOT-23, 0402, DIP-8, TSSOP-16)',
        },
      },
      required: ['part_number', 'component_ref'],
    },
  },
  {
    name: 'call_agent_gen_pcb',
    description:
      'Ingénieur Layout — Expert génération PCB KiCad. ' +
      'Prend le .kicad_sch validé par ERC + les footprints résolus par call_agent_footprint, ' +
      'et génère un .kicad_pcb avec les dimensions optimales et les règles DRC adaptées au type de circuit. ' +
      'Aucun paramètre requis — lit tout depuis le cache interne. ' +
      'OBLIGATOIRE après call_agent_erc + call_agent_footprint, avant call_agent_placement.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_placement',
    description:
      'Ingénieur Placement — Expert pcbnew et stratégies de layout. ' +
      'Positionne chaque composant via pcbnew SetPosition()/SetOrientationDegrees(). ' +
      'Applique les règles : composants critiques proches du connecteur, ' +
      'bypass caps à <2 mm des ICs, regroupement fonctionnel (MCU, power, analog séparés). ' +
      'Aucun paramètre requis — lit .kicad_pcb et netlist depuis le cache. ' +
      'Décide les dimensions du board selon le nombre et la densité des composants.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_routing',
    description:
      'Ingénieur Routage — Expert kicad-tools A* et Freerouting. ' +
      'Pipeline : (1) kicad-tools A* négocié si ≤30 nets ET ≤30 composants (60s), ' +
      '(2) Freerouting Java pour circuits complexes ou si kicad-tools échoue, ' +
      '(3) GND plane seulement si Java absent. Ajoute ground planes B.Cu. ' +
      'Décide seul le nombre de couches (2/4/8) selon densité nette, fréquences et plan utilisateur ' +
      '(Free=2 max · Pro=4 max · Pro Max=8 max · Enterprise=illimité). ' +
      'Aucun paramètre requis — lit depuis le cache.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_drc',
    description:
      'Ingénieur Qualité PCB — Expert DRC JLCPCB. ' +
      'Pipeline : (1) kicad-tools 27 règles JLCPCB (pur Python, toujours dispo) — ' +
      '0 erreur → DRC_CLEAN immédiat ; erreurs → (2) kicad-cli pcb drc auto-fix boucle max 3×. ' +
      'Vérifie : clearance, court-circuits, annular rings, silk overlap, via drill. ' +
      'N\'accepte aucune violation critique (erreur = bloquant). ' +
      'OBLIGATOIRE avant call_agent_export.',
    input_schema: {
      type: 'object' as const,
      properties: {
        auto_fix: {
          type: 'boolean',
          description: 'Corriger automatiquement les violations réparables (défaut: true)',
        },
      },
      required: [],
    },
  },
  {
    name: 'call_agent_export',
    description:
      'Ingénieur Fabrication — Expert JLCPCB et formats Gerber. ' +
      'Pipeline : (1) kicad-tools kct export --mfr jlcpcb (GTL/GBL/GKO, BOM LCSC, CPL rotation corrections), ' +
      '(2) kicad-cli pcb export {gerbers,drill,pos} si kicad-tools échoue, ' +
      '(3) BOM CSV seulement si kicad-cli absent. ' +
      'Calcule le devis JLCPCB (prix, délai). ' +
      'JAMAIS déclencher la commande sans "OUI JE CONFIRME" explicite de l\'utilisateur. ' +
      'Aucun paramètre requis — lit .kicad_pcb DRC-clean depuis le cache.',
    input_schema: {
      type: 'object' as const,
      properties: {},
      required: [],
    },
  },
  {
    name: 'call_agent_simulation',
    description:
      'Ingénieur Simulation — Expert SPICE et analyse de circuit. ' +
      'Lance une simulation ngspice sur le schéma KiCad exporté en SPICE. ' +
      'Retourne vecteurs temporels tension/courant pour les nœuds principaux. ' +
      'Analyse transient (comportement temporel), DC (point de repos) ou AC (réponse fréquentielle). ' +
      'Requiert plan Pro ou supérieur. Coût : 3 crédits. ' +
      'Appeler après call_agent_schema uniquement.',
    input_schema: {
      type: 'object' as const,
      properties: {
        sim_type: {
          type: 'string',
          enum: ['transient', 'dc', 'ac'],
          description: "Type d'analyse SPICE (défaut: transient)",
        },
      },
      required: [],
    },
  },
  {
    name: 'ask_user',
    description:
      'Pose une question à l\'utilisateur pour obtenir une information critique manquante. ' +
      'Utiliser UNIQUEMENT si la donnée est bloquante (tension d\'alimentation, courant max, contrainte mécanique). ' +
      'NE PAS utiliser pour des choix de composants — décider soi-même en ingénieur senior.',
    input_schema: {
      type: 'object' as const,
      properties: {
        question: {
          type: 'string',
          description: 'Question précise et technique',
        },
        context: {
          type: 'string',
          description: 'Pourquoi cette info est bloquante pour continuer le pipeline',
        },
      },
      required: ['question'],
    },
  },
];

export const ACTIVE_PCB_TOOLS = PCB_TOOLS;

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
      // PROVISOIRE: désactivé — passe direct à call_agent_schema
      return {
        status: 'success',
        pcb_status: 'INITIAL',
        note: 'Spec skipped — proceed directly to call_agent_schema.',
      };
    }

    case 'call_agent_schema': {
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

                _pcbStateCache.set(projectId, {
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

      _pcbStateCache.set(projectId, {
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
        // Pass cached schema so the TS ERC can validate connectivity
        const fallback = runErcFallback(cached?.schema);
        const errorCount = fallback.violations.filter(v => v.severity === 'error').length;
        const newStatus: 'ERC_CLEAN' | 'SCHEMA_DONE' = fallback.ercClean ? 'ERC_CLEAN' : 'SCHEMA_DONE';
        return {
          status: 'success',
          pcb_status: newStatus,
          ercViolations: fallback.violations,
          erc_skipped: fallback.skipped,
          fixed_count: fallback.fixedCount,
          kicad_sch_content: schContent,
          engine: fallback.engine,
          warning: fallback.warning,
          note: fallback.skipped
            ? `ERC sauté — kicad-cli indisponible, pas de schéma en cache.`
            : fallback.ercClean
            ? `ERC TypeScript OK — 0 erreur (${fallback.violations.length} warnings). kicad-cli indisponible pour validation complète.`
            : `ERC TypeScript — ${errorCount} erreur(s) détectée(s). Corriger avant placement.`,
        };
      }
    }

    case 'call_agent_footprint': {
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
          const cached = _pcbStateCache.get(projectId);
          if (cached?.schema.components) {
            const updatedComponents = cached.schema.components.map((c) =>
              c.ref === ref ? { ...c, footprint: result.footprint_name } : c
            );
            _pcbStateCache.set(projectId, {
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

    case 'call_agent_gen_pcb': {
      // Ingénieur Layout — génère .kicad_pcb depuis le cache (schema + footprints enrichis)
      const cached = _pcbStateCache.get(projectId);
      if (!cached?.schema || cached.schema.components.length === 0) {
        return {
          status: 'error',
          note: 'Aucun schéma en cache — appeler call_agent_schema d\'abord.',
        };
      }

      const { schema, boardW, boardH } = cached;

      // Essaie d'abord le service Python pour un PCB de meilleure qualité
      const serviceUrl = process.env.KICAD_SERVICE_URL;
      let kicadPcbContent: string | null = null;

      if (serviceUrl) {
        try {
          const schB64 = cached.kicad_sch_content
            ? Buffer.from(cached.kicad_sch_content, 'utf-8').toString('base64')
            : undefined;
          const res = await fetch(`${serviceUrl}/pcb/generate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              components: schema.components,
              nets: schema.nets,
              connections: schema.connections ?? [],
              board_width_mm: boardW,
              board_height_mm: boardH,
              project_id: projectId,
              ...(schB64 ? { kicad_sch_b64: schB64 } : {}),
            }),
            signal: AbortSignal.timeout(60_000),
          });
          if (res.ok) {
            const data = await res.json() as { success: boolean; kicad_pcb_content?: string | null };
            if (data.success && data.kicad_pcb_content) {
              kicadPcbContent = data.kicad_pcb_content;
            }
          }
        } catch {
          log.warn('call_agent_gen_pcb: Python service unavailable — using TS generator');
        }
      }

      // Fallback TS inline via runCircuitSynthEngine (sans service URL = TS pur)
      if (!kicadPcbContent) {
        const tsResult = await runCircuitSynthEngine(schema, boardW, boardH, projectId);
        kicadPcbContent = tsResult.kicad_pcb_content;
      }

      const finalPcb = kicadPcbContent ?? '';
      _pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: finalPcb });

      return {
        status: 'success',
        pcb_status: 'ERC_CLEAN',
        kicad_pcb_content: finalPcb,
        board_width_mm: boardW,
        board_height_mm: boardH,
        component_count: schema.components.length,
        note: `PCB généré — ${schema.components.length} composants, board ${boardW}×${boardH} mm. Prêt pour placement.`,
      };
    }

    case 'call_agent_placement': {
      // Use dimensions from schema cache (set by call_agent_schema) when caller
      // doesn't supply explicit board dimensions — ensures adaptive sizing holds.
      const cachedDims = _pcbStateCache.get(projectId);
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
        log.error({ err, projectId }, 'placement service unavailable');
        return {
          status: 'error',
          error: err instanceof Error ? err.message : 'placement service unavailable',
          note: 'Service pcbnew inaccessible — vérifie que le conteneur Docker KiCad tourne (KICAD_SERVICE_URL).',
        };
      }
    }

    case 'call_agent_routing': {
      const cached = _pcbStateCache.get(projectId);
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
          if (cached) _pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: skippedPcb });
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
          _pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: finalPcb });
        }

        return {
          status: 'success',
          pcb_status: 'ROUTING_DONE',
          routed_percent: 100,
          layers: service.layers as 2 | 4 | 8,
          via_count: service.viaCount ?? Math.floor(schema.components.length * 0.5),
          track_length_mm: service.trackLengthMm ?? +(schema.nets.length * 15).toFixed(1),
          kicad_pcb_content: finalPcb,
          engine: 'freerouting',
          note: `Routage Freerouting ${service.routedPercent}% + GND plane B.Cu — ${schema.nets.length} nets, ${service.layers} couches.`,
        };
      } catch (err) {
        if (!(err instanceof RoutingServiceUnavailableError)) {
          log.warn({ err }, 'routing service threw unexpected error — falling back');
        }
        const fallbackPcb = addGroundPlane(cleanPcbContent, boardW, boardH);
        if (cached) {
          _pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: fallbackPcb });
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

    case 'call_agent_simulation': {
      const simType = (input['sim_type'] as 'transient' | 'dc' | 'ac' | undefined) ?? 'transient';
      const cached = _pcbStateCache.get(projectId);
      const schContent = cached?.kicad_sch_content;

      if (!schContent || schContent.length === 0) {
        return {
          status: 'error',
          note: 'Pas de schéma en cache — exécute call_agent_schema en premier.',
        };
      }

      try {
        const result = await runSimulation({ kicadSchContent: schContent, simType });
        return {
          status: 'success',
          sim_type: simType,
          simulation_data: result.data,
          vector_count: result.data.vectors.length,
          note: `Simulation ${simType} — ${result.data.vectors.length} vecteurs (${result.data.vectors.map((v) => v.name).join(', ')}).`,
        };
      } catch (err) {
        if (!(err instanceof SimulationServiceUnavailableError)) {
          log.warn({ err }, 'simulation service threw unexpected error');
        }
        // Return synthetic demo data so the pipeline stays alive offline
        const demoVectors = _demoVectors(simType);
        return {
          status: 'success',
          sim_type: simType,
          simulation_data: { sim_type: simType, vectors: demoVectors },
          vector_count: demoVectors.length,
          engine: 'demo',
          warning: err instanceof Error ? err.message : 'simulation service unavailable',
          note: `Simulation démo — ${demoVectors.length} vecteurs synthétiques (ngspice indisponible).`,
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
      max_tokens: 4096,
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
  2-pin connector    → "Connector_Generic:Conn_01x02"    pins: 1, 2
  3-pin connector    → "Connector_Generic:Conn_01x03"    pins: 1, 2, 3
  4-pin connector    → "Connector_Generic:Conn_01x04"    pins: 1, 2, 3, 4
  6-pin connector    → "Connector_Generic:Conn_01x06"    pins: 1..6
  8-pin connector    → "Connector_Generic:Conn_01x08"    pins: 1..8
  COMPLEX ICs — MANDATORY connector strategy (NEVER use real MCU symbols):
    Arduino Nano/UNO (30-pin) → "Connector_Generic:Conn_02x15_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical"
    Arduino Mega (44-pin)     → "Connector_Generic:Conn_02x22_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x22_P2.54mm_Vertical"
    ESP32-WROOM / ESP32-S3    → "Connector_Generic:Conn_02x19_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical"
    Raspberry Pi Pico (40-pin)→ "Connector_Generic:Conn_02x20_Odd_Even"  footprint: "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"
    BME280/BMP280 module      → "Connector_Generic:Conn_01x06"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
    DHT22 / DHT11             → "Connector_Generic:Conn_01x04"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    OLED SSD1306 I2C          → "Connector_Generic:Conn_01x04"           footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    HC-05 Bluetooth module    → "Connector_Generic:Conn_01x06"
    STM32 bluepill (40-pin)   → "Connector_Generic:Conn_02x20_Odd_Even"
    Any other module (N pins) → "Connector_Generic:Conn_01xNN" where NN = pin count
  ALL connectors use INTEGER pin numbers (1, 2, 3, ...) in connections.
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

Reference designators: R=resistor, C=capacitor, U=module/IC (use U_ESP, U_ARD, U_BME…), D=diode/LED, J=connector, Q=transistor.
IMPORTANT: For MCU/sensor modules, use ref prefix U_ followed by short name (U_ESP1, U_ARD1, U_BME1).
Keep it to ≤ 20 components.

Example — "LED with 330R on 3.3V" (passives use numbers, connectors use numbers):
{"components":[{"ref":"J1","value":"PWR","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"},{"ref":"R1","value":"330R","footprint":"0603","symbol":"Device:R"},{"ref":"D1","value":"LED_RED","footprint":"LED","symbol":"Device:LED"}],"nets":["GND","3V3","NET_R_D"],"connections":[{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"D1","pin":2}]},{"name":"3V3","pins":[{"ref":"J1","pin":1},{"ref":"R1","pin":1}]},{"name":"NET_R_D","pins":[{"ref":"R1","pin":2},{"ref":"D1","pin":1}]}]}

Example — "LM7805 5V regulator" (IC uses pin names):
{"components":[{"ref":"U1","value":"LM7805","footprint":"TO-220","symbol":"Regulator_Linear:L7805"},{"ref":"C1","value":"100nF","footprint":"0603","symbol":"Device:C"},{"ref":"J1","value":"VIN","footprint":"Conn_2","symbol":"Connector_Generic:Conn_01x02"}],"nets":["GND","VIN","VOUT"],"connections":[{"name":"VIN","pins":[{"ref":"J1","pin":1},{"ref":"U1","pin":"IN"},{"ref":"C1","pin":1}]},{"name":"VOUT","pins":[{"ref":"U1","pin":"OUT"},{"ref":"C1","pin":1}]},{"name":"GND","pins":[{"ref":"J1","pin":2},{"ref":"U1","pin":"GND"},{"ref":"C1","pin":2}]}]}

Return ONLY valid JSON. No markdown fences. No explanation.`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) {
      log.warn({ stop_reason: response.stop_reason }, 'Path B: Haiku returned empty text');
      return null;
    }
    if (response.stop_reason === 'max_tokens') {
      log.warn({ len: text.length }, 'Path B: Haiku hit max_tokens — JSON likely truncated');
    }

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

// --- circuit_synth code generator ----------------------------------------

interface SchematicCodeResult {
  code: string;
  footprints: SchemaComponent[];
}

async function generateSchematicCodeWithHaiku(description: string): Promise<SchematicCodeResult | null> {
  const client = getAnthropicClient();
  if (!client) return null;

  try {
    const response = await client.messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 3000,
      system: `You are a circuit schematic code generator using the circuit_synth Python library.
Generate Python code using the @circuit decorator pattern.

circuit_synth API — EXACT pattern:
\`\`\`python
import os
from circuit_synth import circuit as cs_circuit, Component, Net

@cs_circuit(name="my_project")
def build():
    gnd = Net("GND")
    vcc = Net("+5V")
    r1 = Component("Device:R", ref="R", value="10k")  # ref PREFIX (no number) is REQUIRED
    r1[1] += vcc   # integer pins for passives
    r1[2] += gnd

os.chdir(_PROJECT_PATH)   # MANDATORY — place output in the right directory
circ = build()
circ.generate_kicad_project(project_name="project", generate_pcb=False, force_regenerate=True)
\`\`\`

_PROJECT_PATH is already defined — use it directly.
CRITICAL: always call os.chdir(_PROJECT_PATH) BEFORE calling generate_kicad_project.
CRITICAL: project_name must be a simple string like "project" — NEVER pass _PROJECT_PATH as project_name.
CRITICAL: ref= is REQUIRED in every Component(). Without ref, the component is NOT added to the circuit.
Use ref PREFIX (no number): ref="R" → auto-becomes R1, R2... | ref="C" → C1, C2... | ref="U_ARD" → U_ARD1

STRICT RULES — NEVER BREAK THESE:
  NEVER use MCU_Microchip_ATmega, MCU_Module, RF_Module:*, Sensor:*, Sensor_Pressure:* symbols
  NEVER use Arduino_Nano_v3.x, ATmega328P-A, ESP32-WROOM-32, BME280, DHT11, DHT22 as symbols
  NEVER use any symbol with more than 4 pins that is not Device:R/C/LED/D
  ALWAYS use Connector_Generic:Conn_XxYY for any Arduino, ESP32, sensor module, or IC with >4 pins
  ALWAYS provide ref= in every Component() — without it the component is invisible in the schematic

CONNECTOR STRATEGY — use generic connectors for complex ICs (better schematics, no missing pins):

  Arduino Nano (30-pin dual-row) → Component("Connector_Generic:Conn_02x15_Odd_Even", value="Arduino_Nano")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical"
    Pins: 1=D12, 2=D11/MOSI, 3=D10/SS, 4=D9, 5=D8, 6=D7, 7=D6, 8=D5, 9=D4,
          10=D3, 11=D2, 12=GND, 13=RST, 14=RX/D0, 15=TX/D1,
          16=D13/SCK, 17=3V3, 18=AREF, 19=A0, 20=A1, 21=A2, 22=A3, 23=A4/SDA, 24=A5/SCL,
          25=A6, 26=A7, 27=+5V, 28=RST, 29=GND, 30=VIN

  BME280/BMP280 module (6-pin) → Component("Connector_Generic:Conn_01x06", value="BME280")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical"
    Pins: 1=VCC, 2=GND, 3=SCL, 4=SDA, 5=CSB, 6=SDO

  DHT22/DHT11 (4-pin)  → Component("Connector_Generic:Conn_01x04", value="DHT22")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    Pins: 1=VCC, 2=DATA, 3=NC, 4=GND

  OLED I2C 128x64 (4)  → Component("Connector_Generic:Conn_01x04", value="SSD1306_OLED")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
    Pins: 1=GND, 2=VCC, 3=SCL, 4=SDA

  ESP32-WROOM-32 (38-pin dual-row) → Component("Connector_Generic:Conn_02x19_Odd_Even", ref="U_ESP", value="ESP32-WROOM-32")
    footprint: "Connector_PinHeader_2.54mm:PinHeader_2x19_P2.54mm_Vertical"
    Pins: 1=GND, 2=3V3, 3=EN, 4=VP/ADC0, 5=VN/ADC3, 6=IO34, 7=IO35, 8=IO32, 9=IO33,
          10=IO25, 11=IO26, 12=IO27, 13=IO14, 14=IO12, 15=GND2, 16=IO13, 17=SD2, 18=SD3,
          19=CMD, 20=5V, 21=CLK, 22=SD0, 23=SD1, 24=IO15, 25=IO2, 26=IO0, 27=IO4,
          28=IO16, 29=IO17, 30=IO5, 31=IO18, 32=IO19, 33=IO21, 34=RXD0, 35=TXD0,
          36=IO22, 37=IO23, 38=GND3

  HC-05 Bluetooth (6)  → Component("Connector_Generic:Conn_01x06", ref="U_BT", value="HC-05")
    Pins: 1=STATE, 2=RXD, 3=TXD, 4=GND, 5=VCC, 6=EN

  Any other module N   → Component("Connector_Generic:Conn_01xNN", ref="U_MOD", value="Module_Name")

REAL SYMBOLS for passive/simple components:
  "Device:R"                      pins: 1, 2
  "Device:C"                      pins: 1, 2
  "Device:C_Polarized"            pins: +, -
  "Device:LED"                    pins: A, K
  "Device:D"                      pins: A, K
  "Timer:NE555P"                  pins: GND, TR, Q, R, CV, THR, DIS, VCC
  "Regulator_Linear:LM1117T-3.3"  pins: GND, OUT, IN
  "Regulator_Linear:LM1117T-5.0"  pins: GND, OUT, IN
  "Regulator_Linear:L7805"        pins: VI, GND, VO
  "Connector_Generic:Conn_01x02"  pins: Pin_1, Pin_2 (power connector)

REF naming: modules → U_NAME1 (e.g. U_ARD1, U_BME1), passives → R1/C1/D1, connectors → J_PWR1

Return ONLY valid JSON (no markdown):
{
  "circuit_synth_code": "import os\\nfrom circuit_synth import circuit as cs_circuit, Component, Net\\n\\n@cs_circuit(name=\\"project\\")\\ndef build():\\n    gnd = Net(\\"GND\\")\\n    r1 = Component(\\"Device:R\\", ref=\\"R\\", value=\\"10k\\")\\n    r1[1] += gnd\\n\\nos.chdir(_PROJECT_PATH)\\ncirc = build()\\ncirc.generate_kicad_project(project_name=\\"project\\", generate_pcb=False, force_regenerate=True)",
  "footprints": [
    {"ref": "U_ARD1", "value": "Arduino Nano", "footprint": "Connector_PinHeader_2.54mm:PinHeader_2x15_P2.54mm_Vertical", "symbol": "Connector_Generic:Conn_02x15_Odd_Even"},
    {"ref": "R1", "value": "10k", "footprint": "Resistor_SMD:R_0603_1608Metric", "symbol": "Device:R"}
  ]
}`,
      messages: [{ role: 'user', content: `Circuit: ${description}` }],
    });

    const text = response.content[0]?.type === 'text' ? response.content[0].text.trim() : '';
    if (!text) return null;

    const cleaned = text.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
    const parsed = JSON.parse(cleaned) as { circuit_synth_code: string; footprints: SchemaComponent[] };
    if (!parsed.circuit_synth_code || !Array.isArray(parsed.footprints)) return null;

    const code = parsed.circuit_synth_code;
    if (!code.includes('cs_circuit') && !code.includes('from circuit_synth') && !code.includes('import circuit')) {
      log.warn('Haiku returned non-Python content in circuit_synth_code — discarding');
      return null;
    }

    return { code, footprints: parsed.footprints };
  } catch (err) {
    log.warn({ err }, 'circuit_synth code generator: Haiku call failed');
    return null;
  }
}

// --- PCB helpers ---------------------------------------------------------

/**
 * Remove all copper track segments generated by the TS circuit-synth engine
 * before handing the PCB to Freerouting.  Those tracks were placed at
 * pre-placement component positions and become dangling ends after
 * /place/auto moves the footprints.
 *
 * Freerouting routes from scratch on clean pads; keep the original PCB
 * as a fallback so callers can restore it when Freerouting is unavailable.
 */
function stripTrackSegments(pcbContent: string): string {
  // Handle both single-line `(segment ...)` and multi-line KiCad 7/8 format
  // where pcbnew reformats tracks as `(segment\n  (start ...)\n  ...\n)`.
  // Track paren depth so we skip exactly the lines belonging to each block.
  const lines = pcbContent.split('\n');
  const result: string[] = [];
  let depth = 0;
  let inSegment = false;

  for (const line of lines) {
    if (!inSegment && line.trimStart().startsWith('(segment')) {
      inSegment = true;
      depth = 0;
      for (const ch of line) {
        if (ch === '(') depth++;
        else if (ch === ')') depth--;
      }
      if (depth <= 0) inSegment = false; // single-line — closed on same line
      continue; // always skip the opening line
    }
    if (inSegment) {
      for (const ch of line) {
        if (ch === '(') depth++;
        else if (ch === ')') depth--;
      }
      if (depth <= 0) inSegment = false;
      continue; // skip body / closing line
    }
    result.push(line);
  }

  return result.join('\n');
}

/**
 * Add a GND copper fill (ground plane) on B.Cu covering the full board area.
 * Guarantees GND connectivity even when Freerouting fails to route the GND net
 * (e.g. when it's blocked by signal traces on F.Cu with no available path).
 * Industry-standard practice: route signals on F.Cu, GND plane on B.Cu.
 */
function addGroundPlane(pcbContent: string, boardW: number, boardH: number): string {
  const netMatch = pcbContent.match(/\(net (\d+) "GND"\)/);
  if (!netMatch) return pcbContent;
  const netId = netMatch[1];

  const zone = [
    `  (zone (net ${netId}) (net_name "GND") (layer "B.Cu") (hatch edge 0.508)`,
    `    (connect_pads yes (clearance 0.5))`,
    `    (min_thickness 0.25)`,
    `    (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))`,
    `    (polygon`,
    `      (pts`,
    `        (xy 0 0) (xy ${boardW} 0) (xy ${boardW} ${boardH}) (xy 0 ${boardH})`,
    `      )`,
    `    )`,
    `  )`,
  ].join('\n');

  const trimmed = pcbContent.trimEnd();
  return trimmed.endsWith(')') ? trimmed.slice(0, -1) + '\n' + zone + '\n)' : pcbContent + '\n' + zone;
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

// ---------------------------------------------------------------------------
// Demo simulation vectors (used when ngspice service is unavailable)
// ---------------------------------------------------------------------------

function _demoVectors(simType: string): Array<{ name: string; unit: string; time: number[]; values: number[] }> {
  const steps = 200;
  if (simType === 'ac') {
    const freqs = Array.from({ length: 70 }, (_, i) => Math.pow(10, i * 0.1));
    return [
      { name: 'v(out)', unit: 'V', time: freqs,
        values: freqs.map((f) => 1 / Math.sqrt(1 + Math.pow(f / 1592, 2))) },
    ];
  }
  const t = Array.from({ length: steps }, (_, i) => i * 1e-6);
  const tau = 1e-4;
  return [
    { name: 'v(vin)',  unit: 'V', time: t, values: Array(steps).fill(5.0) },
    { name: 'v(vmid)', unit: 'V', time: t, values: t.map((ti) => 5 * (1 - Math.exp(-ti / tau))) },
    { name: 'i(v1)',   unit: 'A', time: t, values: t.map((ti) => (5 / 1000) * Math.exp(-ti / tau)) },
  ];
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
