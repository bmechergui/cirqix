/**
 * HTTP client for the FastAPI export microservice.
 *
 * POSTs the base64-encoded `.kicad_pcb` to `${KICAD_SERVICE_URL}/export/all`
 * and returns the manufacturing zip + quote. Throws ``ExportServiceUnavailableError``
 * on any failure so the caller can fall back to a minimal BOM-only path.
 */

import pino from 'pino';

const log = pino({
  name: 'cirqix.agents.export-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const EXPORT_TIMEOUT_MS = 60_000;

export class ExportServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'ExportServiceUnavailableError';
  }
}

export interface RealExportInput {
  kicadPcbContent: string;
  projectId: string;
}

export interface RealExportResult {
  files: string[];
  zipB64?: string;
  quoteUsd: number;
  leadTimeDays: number;
  skipped: boolean;
  warning?: string;
}

interface ServiceResponseBody {
  files?: unknown;
  zip_b64?: unknown;
  quote_usd?: unknown;
  lead_time_days?: unknown;
  skipped?: unknown;
  warning?: unknown;
}

export async function runRealExport(input: RealExportInput): Promise<RealExportResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — export service unavailable');
    throw new ExportServiceUnavailableError('KICAD_SERVICE_URL not configured');
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/export/all`;
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    project_id: input.projectId,
  });

  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(EXPORT_TIMEOUT_MS),
    });
  } catch (err) {
    log.warn({ err, url }, 'export service: fetch failed');
    throw new ExportServiceUnavailableError(
      err instanceof Error ? err.message : 'fetch failed',
      err,
    );
  }

  if (!response.ok) {
    log.warn({ status: response.status, url }, 'export service: non-2xx response');
    throw new ExportServiceUnavailableError(`export service returned ${response.status}`);
  }

  let parsed: ServiceResponseBody;
  try {
    parsed = (await response.json()) as ServiceResponseBody;
  } catch (err) {
    log.warn({ err }, 'export service: invalid JSON response');
    throw new ExportServiceUnavailableError('invalid JSON response', err);
  }

  const skipped = parsed.skipped === true;
  const files = Array.isArray(parsed.files)
    ? parsed.files.filter((f): f is string => typeof f === 'string')
    : [];
  const quoteUsd = typeof parsed.quote_usd === 'number' ? parsed.quote_usd : 0;
  const leadTimeDays = typeof parsed.lead_time_days === 'number' ? parsed.lead_time_days : 0;

  const result: RealExportResult = {
    files,
    quoteUsd,
    leadTimeDays,
    skipped,
  };
  if (typeof parsed.zip_b64 === 'string' && parsed.zip_b64.length > 0) {
    result.zipB64 = parsed.zip_b64;
  }
  if (typeof parsed.warning === 'string') result.warning = parsed.warning;
  return result;
}
