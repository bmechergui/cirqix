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
}

export const pcbStateCache = new Map<string, PcbStateCacheEntry>();
