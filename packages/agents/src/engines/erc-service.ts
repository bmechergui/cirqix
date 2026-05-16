/**
 * HTTP client for the FastAPI ERC microservice.
 *
 * POSTs the base64-encoded `.kicad_sch` content to `${KICAD_SERVICE_URL}/erc`
 * and returns the parsed result. Throws ``ErcServiceUnavailableError`` on any
 * failure (missing env var, non-2xx, network error, timeout, malformed JSON)
 * so the caller can fall back to the TS skip path.
 */

import pino from 'pino';
import type { ERCViolation } from '@layrix/types';

const log = pino({
  name: 'layrix.agents.erc-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const ERC_TIMEOUT_MS = 10_000;

export class ErcServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'ErcServiceUnavailableError';
  }
}

export interface RealErcInput {
  kicadSchContent: string;
  autoFix: boolean;
}

export interface RealErcResult {
  ercClean: boolean;
  violations: ERCViolation[];
  fixedCount: number;
  /** New .kicad_sch content (UTF-8 text) only when auto-fix changed the file. */
  kicadSchContent?: string;
  skipped: boolean;
  warning?: string;
}

interface ServiceResponseBody {
  erc_clean?: unknown;
  violations?: unknown;
  fixed_count?: unknown;
  kicad_sch_b64?: unknown;
  skipped?: unknown;
  warning?: unknown;
}

function asViolation(value: unknown): ERCViolation | null {
  if (!value || typeof value !== 'object') return null;
  const v = value as Record<string, unknown>;
  if (typeof v['id'] !== 'string') return null;
  const severity = v['severity'];
  if (severity !== 'error' && severity !== 'warning') return null;
  if (typeof v['message'] !== 'string') return null;
  const out: ERCViolation = {
    id: v['id'],
    severity,
    message: v['message'],
  };
  if (typeof v['type'] === 'string') out.type = v['type'];
  if (typeof v['ref'] === 'string') out.ref = v['ref'];
  if (typeof v['pin'] === 'string') out.pin = v['pin'];
  if (typeof v['x_mm'] === 'number') out.x_mm = v['x_mm'];
  if (typeof v['y_mm'] === 'number') out.y_mm = v['y_mm'];
  return out;
}

export async function runRealErc(input: RealErcInput): Promise<RealErcResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — ERC service unavailable');
    throw new ErcServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/erc`;
  const body = JSON.stringify({
    kicad_sch_b64: Buffer.from(input.kicadSchContent, 'utf-8').toString('base64'),
    auto_fix: input.autoFix,
  });

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(ERC_TIMEOUT_MS),
    });
  } catch (err) {
    log.warn({ err, url }, 'ERC service: fetch failed');
    throw new ErcServiceUnavailableError(
      err instanceof Error ? err.message : 'fetch failed',
      err,
    );
  }

  if (!response.ok) {
    log.warn({ status: response.status, url }, 'ERC service: non-2xx response');
    throw new ErcServiceUnavailableError(`ERC service returned ${response.status}`);
  }

  let parsed: ServiceResponseBody;
  try {
    parsed = (await response.json()) as ServiceResponseBody;
  } catch (err) {
    log.warn({ err }, 'ERC service: invalid JSON response');
    throw new ErcServiceUnavailableError('invalid JSON response', err);
  }

  const ercClean = parsed.erc_clean === true;
  const skipped = parsed.skipped === true;
  const fixedCount = typeof parsed.fixed_count === 'number' ? parsed.fixed_count : 0;
  const violations = Array.isArray(parsed.violations)
    ? parsed.violations
        .map(asViolation)
        .filter((v): v is ERCViolation => v !== null)
    : [];

  const result: RealErcResult = {
    ercClean,
    violations,
    fixedCount,
    skipped,
  };
  if (typeof parsed.kicad_sch_b64 === 'string' && parsed.kicad_sch_b64.length > 0) {
    result.kicadSchContent = Buffer.from(parsed.kicad_sch_b64, 'base64').toString('utf-8');
  }
  if (typeof parsed.warning === 'string') {
    result.warning = parsed.warning;
  }
  return result;
}
