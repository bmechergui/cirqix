import Anthropic from '@anthropic-ai/sdk';
import pino from 'pino';
import type { SchemaJson } from '../engines/engine-router';
import type { Plan } from '@cirqix/types';

// --- Module-level singletons (review fix HIGH-1: avoid recreating per call) ---

export const log = pino({ name: 'cirqix.agents.tools', level: process.env['LOG_LEVEL'] ?? 'info' });

let _anthropic: Anthropic | null = null;
export function getAnthropicClient(): Anthropic | null {
  if (_anthropic) return _anthropic;
  const apiKey = process.env['ANTHROPIC_API_KEY'];
  if (!apiKey) return null;
  _anthropic = new Anthropic({ apiKey });
  return _anthropic;
}

// Persistent PCB state across tool calls within one orchestrator run.
// Keyed by projectId — populated by call_agent_schema and used by placement.
// Single ES-module singleton: every handler imports THIS map instance so the
// pipeline state stays shared across the split tool modules.
export interface PcbStateCacheEntry {
  schema: SchemaJson;
  boardW: number;
  boardH: number;
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
  /**
   * Outcome of the last real DRC execution for this project board.
   * - `true`  → DRC ran and found 0 violations (pcb_status DRC_CLEAN)
   * - `false` → DRC ran and found remaining violations (ROUTING_DONE)
   * - absent  → DRC never ran successfully on the current board
   *
   * Written only by handleDrc. Read by handleExport so export never fabricates
   * a validation status. Cleared when placement/routing/gen_pcb overwrite the
   * board (validation would be stale).
   */
  drc_clean?: boolean;
}

export const pcbStateCache = new Map<string, PcbStateCacheEntry>();

/**
 * Plan de l'utilisateur qui a lancé le pipeline, par projet.
 *
 * DÉLIBÉRÉMENT séparé de `pcbStateCache`. Le plan n'est pas un état de board :
 * c'est du contexte de run, et il gouverne des droits réels — aujourd'hui le
 * plafond de couches appliqué par `handleRouting`.
 *
 * Le mettre DANS `pcbStateCache` serait un piège : neuf handlers y écrivent, et
 * plusieurs — `handleSchema` le premier, donc dès la première étape —
 * réécrivent l'entrée EN ENTIER plutôt que de l'étendre. Le plan serait effacé
 * en silence, chaque compte retomberait sur `free`, et les abonnés payants
 * seraient plafonnés à 2 couches sans qu'aucun test de handler ne le voie.
 *
 * Une map séparée est immunisée contre ces réécritures.
 */
const projectPlanCache = new Map<string, Plan>();

/** Sème le plan à l'entrée du pipeline. Appelé par la route agent. */
export function setProjectPlan(projectId: string, plan: Plan): void {
  projectPlanCache.set(projectId, plan);
}

/**
 * Plan du projet, ou `undefined`. Les appelants DOIVENT passer par
 * `entitlementsForPlan` / `maxLayersForPlan`, qui retombent sur `free` : une
 * omission de plumbing ne doit jamais ouvrir de droits.
 */
export function getProjectPlan(projectId: string): Plan | undefined {
  return projectPlanCache.get(projectId);
}

/** Libère le contexte de run — appelé en fin de pipeline. */
export function clearProjectPlan(projectId: string): void {
  projectPlanCache.delete(projectId);
}

/**
 * After keepBestDrc / keepBestRouting retains an earlier attempt, rewrite the
 * cache so handleExport (and any later tool) sees the same board as `result`.
 * No-op when the result has no board content or the project has no cache entry.
 */
export function syncPcbCacheFromResult(
  projectId: string,
  result: Record<string, unknown>,
): void {
  const content = result['kicad_pcb_content'];
  if (typeof content !== 'string' || content.length === 0) return;
  const cached = pcbStateCache.get(projectId);
  if (!cached) return;

  const next: PcbStateCacheEntry = {
    ...cached,
    kicad_pcb_content: content,
  };
  if (typeof result['drc_clean'] === 'boolean') {
    next.drc_clean = result['drc_clean'];
  }
  pcbStateCache.set(projectId, next);
}
