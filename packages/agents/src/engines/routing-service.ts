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
import { buildKicadServiceHeaders } from './kicad-service-auth';
import { longCallFetch } from './long-call-transport';
import { routingSearchBudgetS, routingAbortMs } from './routing-budget';

const log = pino({
  name: 'cirqix.agents.routing-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});



export class RoutingServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'RoutingServiceUnavailableError';
  }
}

export interface RealRoutingInput {
  kicadPcbContent: string;
  layers: 2 | 4 | 8;
  /**
   * Nom sous lequel le service publie l'avancement du routage, pour qu'une
   * AUTRE requête puisse le lire pendant les vingt minutes que dure l'appel.
   * Absente, le service ne publie rien et le routage se déroule à l'identique.
   * La produire avec `progressKeyFor` : une clé hors alphabet ferait répondre
   * 422 au service, donc échouer le routage pour un simple indicateur.
   */
  progressKey?: string;
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
  /** Quel niveau du service a réellement produit le board. */
  engine?: string;
}

interface ServiceResponseBody {
  kicad_pcb_b64?: unknown;
  routed_percent?: unknown;
  layers?: unknown;
  via_count?: unknown;
  track_length_mm?: unknown;
  skipped?: unknown;
  warning?: unknown;
  engine?: unknown;
}

/**
 * Moteur annoncé par le service — jamais deviné.
 *
 * `handlers/routing.ts` écrivait `engine: 'kicad-tools'` EN DUR et composait sa
 * note avec. Or la cascade du service a quatre niveaux : sur un board dense,
 * kicad-tools rend 91 %, sous le seuil, et c'est Freerouting qui livre. L'
 * utilisateur lisait pourtant « Routage kicad-tools ».
 *
 * Une attribution fausse envoie chercher au mauvais endroit — elle a coûté
 * plusieurs heures le 2026-08-20. Un service plus ancien qui ne renvoie pas le
 * champ ne se voit donc attribuer AUCUN moteur : mieux vaut se taire que
 * désigner le mauvais.
 */
export function readRoutingEngine(body: { engine?: unknown }): string | undefined {
  return typeof body.engine === 'string' && body.engine.length > 0
    ? body.engine
    : undefined;
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
  // Budget de RECHERCHE accordé au routeur — pas une limite de patience :
  // `kct route` rend la main dès 100 % atteint. Voir `routing-budget.ts` pour
  // pourquoi l'ancienne heuristique (180 s sur 4 couches) bridait la complétion.
  const timeoutS = routingSearchBudgetS(input.layers);
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    layers: input.layers,
    timeout_s: timeoutS,
    // Absente par defaut : un appelant qui ne suit pas la progression route
    // exactement comme avant, et le service ne publie rien.
    ...(input.progressKey ? { progress_key: input.progressKey } : {}),
  });

  let response: Response;
  try {
    response = await longCallFetch(url, {
      method: 'POST',
      headers: buildKicadServiceHeaders(),
      body,
      signal: AbortSignal.timeout(routingAbortMs(input.layers)),
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
  const engine = readRoutingEngine(parsed);
  if (engine) result.engine = engine;
  if (typeof parsed.warning === 'string') result.warning = parsed.warning;
  return result;
}
