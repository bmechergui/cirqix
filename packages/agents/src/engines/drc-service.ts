/**
 * HTTP client for the FastAPI DRC microservice.
 *
 * POSTs the base64-encoded `.kicad_pcb` to `${KICAD_SERVICE_URL}/drc/auto`
 * and returns the parsed result. Throws ``DrcServiceUnavailableError`` on any
 * failure so the caller can fall back to the inline skip path.
 */

import pino from 'pino';
import type { DRCViolation } from '@cirqix/types';

const log = pino({
  name: 'cirqix.agents.drc-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const DRC_TIMEOUT_MS = 30_000;

export class DrcServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'DrcServiceUnavailableError';
  }
}

export interface RealDrcInput {
  kicadPcbContent: string;
  autoFix: boolean;
}

export interface RealDrcResult {
  drcClean: boolean;
  violations: DRCViolation[];
  fixedCount: number;
  /** Updated .kicad_pcb (UTF-8 text) only when auto-fix changed the file. */
  kicadPcbContent?: string;
  skipped: boolean;
  warning?: string;
}

interface ServiceResponseBody {
  drc_clean?: unknown;
  violations?: unknown;
  fixed_count?: unknown;
  kicad_pcb_b64?: unknown;
  skipped?: unknown;
  warning?: unknown;
}

function asViolation(value: unknown): DRCViolation | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (typeof v['id'] !== 'string') return null;
  const severity = v['severity'];
  if (severity !== 'error' && severity !== 'warning') return null;
  if (typeof v['message'] !== 'string') return null;
  const out: DRCViolation = {
    id: v['id'],
    severity,
    message: v['message'],
    x_mm: typeof v['x_mm'] === 'number' ? v['x_mm'] : 0,
    y_mm: typeof v['y_mm'] === 'number' ? v['y_mm'] : 0,
  };
  if (typeof v['layer'] === 'string') out.layer = v['layer'];
  return out;
}

export async function runRealDrc(input: RealDrcInput): Promise<RealDrcResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — DRC service unavailable');
    throw new DrcServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/drc/auto`;
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    auto_fix: input.autoFix,
  });

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(DRC_TIMEOUT_MS),
    });
  } catch (err) {
    log.warn({ err, url }, 'DRC service: fetch failed');
    throw new DrcServiceUnavailableError(
      err instanceof Error ? err.message : 'fetch failed',
      err,
    );
  }

  if (!response.ok) {
    log.warn({ status: response.status, url }, 'DRC service: non-2xx response');
    throw new DrcServiceUnavailableError(`DRC service returned ${response.status}`);
  }

  let parsed: ServiceResponseBody;
  try {
    parsed = (await response.json()) as ServiceResponseBody;
  } catch (err) {
    log.warn({ err }, 'DRC service: invalid JSON response');
    throw new DrcServiceUnavailableError('invalid JSON response', err);
  }

  const drcClean = parsed.drc_clean === true;
  const skipped = parsed.skipped === true;
  const fixedCount = typeof parsed.fixed_count === 'number' ? parsed.fixed_count : 0;
  const violations = Array.isArray(parsed.violations)
    ? parsed.violations
        .map(asViolation)
        .filter((v): v is DRCViolation => v !== null)
    : [];

  const result: RealDrcResult = {
    drcClean,
    violations,
    fixedCount,
    skipped,
  };
  if (typeof parsed.kicad_pcb_b64 === 'string' && parsed.kicad_pcb_b64.length > 0) {
    result.kicadPcbContent = Buffer.from(parsed.kicad_pcb_b64, 'base64').toString('utf-8');
  }
  if (typeof parsed.warning === 'string') result.warning = parsed.warning;
  return result;
}
