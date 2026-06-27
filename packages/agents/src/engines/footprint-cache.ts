/**
 * pgvector footprint cache — Step 1.5 in the resolution cascade.
 *
 * Two lookup strategies:
 *   a) Exact/ILIKE match on part_number — no API key needed, instant
 *   b) OpenAI embedding similarity (<-> operator) — requires OPENAI_API_KEY
 *
 * Both are skipped gracefully when Supabase or OpenAI is not configured.
 * Cache writes (upsert) are fire-and-forget and never block the cascade.
 */

import { createAdminSupabaseClient } from '@cirqix/db';
import pino from 'pino';
import type { FootprintResult, FootprintSource } from './footprint-service';

const log = pino({ name: 'cirqix.agents.footprint-cache', level: process.env['LOG_LEVEL'] ?? 'info' });

const EMBEDDING_MODEL = 'text-embedding-3-small';
const EMBEDDING_DIMS = 1536;
const SIMILARITY_THRESHOLD = 0.80;
const EMBED_TIMEOUT_MS = 5_000;

// ─── OpenAI embedding (optional, requires OPENAI_API_KEY) ────────────────────

async function generateEmbedding(text: string): Promise<number[] | null> {
  const apiKey = process.env['OPENAI_API_KEY'];
  if (!apiKey) return null;

  try {
    const res = await fetch('https://api.openai.com/v1/embeddings', {
      method: 'POST',
      headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: EMBEDDING_MODEL, input: text, dimensions: EMBEDDING_DIMS }),
      signal: AbortSignal.timeout(EMBED_TIMEOUT_MS),
    });
    if (!res.ok) return null;
    const body = await res.json() as { data?: Array<{ embedding: number[] }> };
    return body.data?.[0]?.embedding ?? null;
  } catch (err) {
    log.warn({ err }, 'embedding generation failed — skipping similarity search');
    return null;
  }
}

// ─── Row type returned by RPCs ────────────────────────────────────────────────

interface FootprintRow {
  id: string;
  name: string;
  part_number: string | null;
  source: string | null;
  kicad_mod: string | null;
  similarity?: number;
}

function rowToResult(row: FootprintRow): FootprintResult {
  return {
    footprint_name: row.name,
    source: (row.source ?? 'kicad_official') as FootprintSource,
    ...(row.kicad_mod ? { kicad_mod: row.kicad_mod } : {}),
    note: `Footprint cache Cirqix (${row.source ?? 'kicad_official'}) : "${row.part_number ?? row.name}".`,
  };
}

// ─── Public: lookup ───────────────────────────────────────────────────────────

/**
 * Search the community footprint cache.
 * Returns null if nothing found or if Supabase is not configured.
 */
export async function lookupFootprintCache(
  partNumber: string,
  packageHint?: string,
): Promise<FootprintResult | null> {
  let sb: ReturnType<typeof createAdminSupabaseClient>;
  try {
    sb = createAdminSupabaseClient();
  } catch {
    return null;
  }

  // Strategy a — exact/ILIKE part number
  try {
    const { data, error } = await (sb as unknown as {
      rpc: (fn: string, args: Record<string, unknown>) => Promise<{ data: unknown; error: unknown }>;
    }).rpc('search_footprint_by_part_number', { p_part_number: partNumber });

    if (!error && Array.isArray(data) && data.length > 0) {
      log.info({ partNumber }, 'step 1.5 hit: exact part number cache');
      return rowToResult(data[0] as FootprintRow);
    }
  } catch (err) {
    log.warn({ err }, 'footprint cache: exact search error');
  }

  // Strategy b — embedding similarity (only when OPENAI_API_KEY is set)
  const query = packageHint ? `${partNumber} ${packageHint}` : partNumber;
  const embedding = await generateEmbedding(query);
  if (!embedding) return null;

  try {
    const { data, error } = await (sb as unknown as {
      rpc: (fn: string, args: Record<string, unknown>) => Promise<{ data: unknown; error: unknown }>;
    }).rpc('search_footprint_by_embedding', {
      p_embedding: `[${embedding.join(',')}]`,
      p_threshold: SIMILARITY_THRESHOLD,
    });

    if (!error && Array.isArray(data) && data.length > 0) {
      const row = data[0] as FootprintRow;
      log.info({ partNumber, similarity: row.similarity }, 'step 1.5 hit: embedding similarity cache');
      return rowToResult(row);
    }
  } catch (err) {
    log.warn({ err }, 'footprint cache: embedding search error');
  }

  return null;
}

// ─── Public: write-back ───────────────────────────────────────────────────────

/**
 * Persist a resolved footprint into the community cache.
 * Generates embedding if OPENAI_API_KEY is available.
 * Fire-and-forget — never throws.
 */
export async function cacheFootprintResult(
  partNumber: string,
  packageHint: string | undefined,
  result: FootprintResult,
): Promise<void> {
  let sb: ReturnType<typeof createAdminSupabaseClient>;
  try {
    sb = createAdminSupabaseClient();
  } catch {
    return;
  }

  const query = packageHint ? `${partNumber} ${packageHint}` : partNumber;
  const embedding = await generateEmbedding(query);

  try {
    await (sb as unknown as {
      rpc: (fn: string, args: Record<string, unknown>) => Promise<{ data: unknown; error: unknown }>;
    }).rpc('upsert_community_footprint', {
      p_name: result.footprint_name,
      p_part_number: partNumber,
      p_source: result.source,
      p_kicad_mod: result.kicad_mod ?? null,
      p_embedding: embedding ? `[${embedding.join(',')}]` : null,
    });
    log.debug({ partNumber, source: result.source }, 'footprint result cached');
  } catch (err) {
    log.warn({ err }, 'footprint cache write failed — ignored');
  }
}
