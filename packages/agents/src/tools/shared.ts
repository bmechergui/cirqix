import Anthropic from '@anthropic-ai/sdk';
import pino from 'pino';
import type { SchemaJson } from '../engines/engine-router';

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
