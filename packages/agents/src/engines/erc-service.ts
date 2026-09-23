/**
 * HTTP client for the FastAPI ERC microservice.
 *
 * POSTs the base64-encoded `.kicad_sch` content to `${KICAD_SERVICE_URL}/erc`
 * and returns the parsed result. Throws ``ErcServiceUnavailableError`` on any
 * failure (missing env var, non-2xx, network error, timeout, malformed JSON)
 * so the caller can fall back to the TS skip path.
 */

import pino from 'pino';
import type { ERCViolation } from '@cirqix/types';
import { buildKicadServiceHeaders } from './kicad-service-auth';

const log = pino({
  name: 'cirqix.agents.erc-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

/**
 * Budget client de `/erc` — il doit couvrir le pire cas que le SERVICE s'accorde.
 *
 * ⚠️ Mesuré le 2026-09-15 (run NE555 `1b2c2ab4`) : à 10 s, le client raccrochait
 * pendant que le service travaillait encore — validation journalisée, aucun
 * `POST /erc` en retour. Le handler retombait sur l'ERC TypeScript et promouvait
 * `ERC_CLEAN` sous la note « kicad-cli indisponible », alors que kicad-cli
 * l'était parfaitement. Isolé, le même schéma passe en 3,6-4,1 s ; mais
 * `routers/erc.py` s'accorde jusqu'à 3 passes kicad-cli de 30 s chacune
 * (+ ~3 s de validation kicad-tools). 120 s couvre ces 93 s avec marge.
 *
 * Garde (lit les limites dans `routers/erc.py`) : tests/erc-budget.test.ts.
 */
// ⚠️ 735 s, et ce n'est pas un chiffre rond : c'est le PIRE CAS QUE LE SERVICE
// S'ACCORDE, lu dans `routers/erc.py` — `_MAX_ITERATIONS` (3) passes de
// `kicad-cli sch erc` plafonnées à `_KICAD_CLI_TIMEOUT_PLAFOND_S` (240 s),
// plus 15 s pour la validation kicad-tools qui les précède et le transport.
//
// Il valait 120 s jusqu'au 2026-09-23, quand le budget du service était de
// 30 s à plat. Ce jour-là, deux cartes du banc ont été perdues parce que
// `kicad-cli` dépassait ces 30 s sur un schéma de 140 à 190 ko ; le service
// déduit désormais son budget de la taille du fichier, et le client doit
// suivre. Un budget relevé à une seule extrémité est décoratif — c'est la
// leçon des QUATRE frontières du routage, réapprise ici.
//
// `erc-budget.test.ts` lit les deux constantes Python et échoue si l'écart se
// rouvre.
export const ERC_TIMEOUT_MS = 735_000;

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
      headers: buildKicadServiceHeaders(),
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
