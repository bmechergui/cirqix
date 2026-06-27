/**
 * HTTP client for the FastAPI routing microservice (Freerouting).
 *
 * POSTs the base64-encoded `.kicad_pcb` content to `${KICAD_SERVICE_URL}/route/auto`
 * and returns the parsed result. Throws ``RoutingServiceUnavailableError`` on any
 * failure so the caller can fall back to the inline Circuit-Synth trace generator.
 *
 * Timeout is generous (90 s) since Freerouting can take 30–60 s on a 4-layer
 * board; the service itself caps at its own internal limit.
 */

import pino from 'pino';

const log = pino({
  name: 'cirqix.agents.routing-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const ROUTING_TIMEOUT_MS = 90_000;

export class RoutingServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'RoutingServiceUnavailableError';
  }
}

export interface RealRoutingInput {
  kicadPcbContent: string;
  layers: 2 | 4 | 8;
}

export interface RealRoutingResult {
  /** Updated .kicad_pcb (UTF-8 text). Undefined when service skipped routing. */
  kicadPcbContent?: string;
  routedPercent: number;
  layers: number;
  viaCount?: number;
  trackLengthMm?: number;
  skipped: boolean;
  warning?: string;
}

interface ServiceResponseBody {
  kicad_pcb_b64?: unknown;
  routed_percent?: unknown;
  layers?: unknown;
  via_count?: unknown;
  track_length_mm?: unknown;
  skipped?: unknown;
  warning?: unknown;
}

export async function runRealRouting(
  input: RealRoutingInput,
): Promise<RealRoutingResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — routing service unavailable');
    throw new RoutingServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/route/auto`;
  // Per-layer timeout heuristic — capped by ROUTING_TIMEOUT_MS for safety.
  const timeoutS = Math.min(60 + input.layers * 30, ROUTING_TIMEOUT_MS / 1000);
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    layers: input.layers,
    timeout_s: timeoutS,
  });

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(ROUTING_TIMEOUT_MS),
    });
  } catch (err) {
    log.warn({ err, url }, 'routing service: fetch failed');
    throw new RoutingServiceUnavailableError(
      err instanceof Error ? err.message : 'fetch failed',
      err,
    );
  }

  if (!response.ok) {
    log.warn({ status: response.status, url }, 'routing service: non-2xx response');
    throw new RoutingServiceUnavailableError(
      `routing service returned ${response.status}`,
    );
  }

  let parsed: ServiceResponseBody;
  try {
    parsed = (await response.json()) as ServiceResponseBody;
  } catch (err) {
    log.warn({ err }, 'routing service: invalid JSON response');
    throw new RoutingServiceUnavailableError('invalid JSON response', err);
  }

  const skipped = parsed.skipped === true;
  const routedPercent =
    typeof parsed.routed_percent === 'number' ? parsed.routed_percent : 0;
  const layers = typeof parsed.layers === 'number' ? parsed.layers : input.layers;

  const result: RealRoutingResult = {
    routedPercent,
    layers,
    skipped,
  };
  if (typeof parsed.kicad_pcb_b64 === 'string' && parsed.kicad_pcb_b64.length > 0) {
    result.kicadPcbContent = Buffer.from(parsed.kicad_pcb_b64, 'base64').toString('utf-8');
  }
  if (typeof parsed.via_count === 'number') result.viaCount = parsed.via_count;
  if (typeof parsed.track_length_mm === 'number') result.trackLengthMm = parsed.track_length_mm;
  if (typeof parsed.warning === 'string') result.warning = parsed.warning;
  return result;
}
