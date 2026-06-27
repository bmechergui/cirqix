/**
 * Thin HTTP client for the FastAPI placement microservice.
 *
 * POSTs the base64-encoded `.kicad_pcb` content to `${KICAD_SERVICE_URL}/place/auto`
 * and returns the decoded result. Throws `PlacementServiceUnavailableError` on
 * any failure (missing env var, non-2xx status, network error, timeout, malformed
 * JSON) so the caller can fall back to the pure TS planner.
 */

import pino from 'pino';

const log = pino({
  name: 'cirqix.agents.placement-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const PLACEMENT_TIMEOUT_MS = 10_000;

export class PlacementServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'PlacementServiceUnavailableError';
  }
}

export interface RealPlacementInput {
  /** Raw `.kicad_pcb` file content (UTF-8 text). */
  kicadPcbContent: string;
  boardWidthMm: number;
  boardHeightMm: number;
}

export interface RealPlacementResult {
  /** Updated `.kicad_pcb` file content (UTF-8 text). */
  kicadPcbContent: string;
  positions: Array<{ ref: string; x_mm: number; y_mm: number }>;
}

interface ServiceResponseBody {
  kicad_pcb_b64?: unknown;
  placed_count?: unknown;
  positions?: unknown;
}

function isValidPosition(value: unknown): value is { ref: string; x_mm: number; y_mm: number } {
  if (!value || typeof value !== 'object') return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v['ref'] === 'string' &&
    typeof v['x_mm'] === 'number' &&
    typeof v['y_mm'] === 'number'
  );
}

export async function runRealPlacement(
  input: RealPlacementInput,
): Promise<RealPlacementResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — placement service unavailable');
    throw new PlacementServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/place/auto`;
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    board_width_mm: input.boardWidthMm,
    board_height_mm: input.boardHeightMm,
  });

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(PLACEMENT_TIMEOUT_MS),
    });
  } catch (err) {
    log.warn({ err, url }, 'placement service: fetch failed');
    throw new PlacementServiceUnavailableError(
      err instanceof Error ? err.message : 'fetch failed',
      err,
    );
  }

  if (!response.ok) {
    log.warn({ status: response.status, url }, 'placement service: non-2xx response');
    throw new PlacementServiceUnavailableError(
      `placement service returned ${response.status}`,
    );
  }

  let parsed: ServiceResponseBody;
  try {
    parsed = (await response.json()) as ServiceResponseBody;
  } catch (err) {
    log.warn({ err, url }, 'placement service: invalid JSON response');
    throw new PlacementServiceUnavailableError('invalid JSON response', err);
  }

  if (typeof parsed.kicad_pcb_b64 !== 'string') {
    throw new PlacementServiceUnavailableError('missing kicad_pcb_b64 in response');
  }
  const positions = Array.isArray(parsed.positions)
    ? parsed.positions.filter(isValidPosition)
    : [];

  const decoded = Buffer.from(parsed.kicad_pcb_b64, 'base64').toString('utf-8');
  return { kicadPcbContent: decoded, positions };
}
