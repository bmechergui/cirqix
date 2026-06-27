/**
 * reasoning-service.ts — client de l'agent Reasoner du microservice KiCad.
 *
 * POST le `.kicad_pcb` routé partiellement à `${KICAD_SERVICE_URL}/reason/auto`.
 * Le service débloque les nets restants via le reasoner LLM (Claude Haiku) ou
 * l'heuristique `kct reason --auto-route`, et renvoie le board + le log des
 * actions IA (pour l'affichage UI/SSE).
 */
import pino from 'pino';

const log = pino({
  name: 'cirqix.agents.reasoning-service',
  level: process.env['LOG_LEVEL'] ?? 'info',
});

const REASON_TIMEOUT_MS = 180_000;

export interface ReasonerInput {
  kicadPcbContent: string;
  maxSteps?: number;
}

export interface ReasonerResult {
  /** Board mis à jour (UTF-8). Undefined si le service n'a rien renvoyé. */
  kicadPcbContent?: string | undefined;
  routedPercent: number;
  /** Log lisible des actions IA, pour l'UI/SSE. */
  steps: string[];
  usedLlm: boolean;
  warning?: string | undefined;
}

interface ReasonResponseBody {
  kicad_pcb_b64?: unknown;
  routed_percent?: unknown;
  steps?: unknown;
  used_llm?: unknown;
  warning?: unknown;
}

/**
 * Appelle l'agent reasoner. Sur indisponibilité du service, renvoie un résultat
 * neutre (0%, aucune étape) plutôt que de lever — le routage partiel reste valide.
 */
export async function runReasoner(input: ReasonerInput): Promise<ReasonerResult> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) {
    log.warn('KICAD_SERVICE_URL not set — reasoner unavailable');
    return { routedPercent: 0, steps: [], usedLlm: false, warning: 'service indisponible' };
  }

  const url = `${baseUrl.replace(/\/+$/, '')}/reason/auto`;
  const body = JSON.stringify({
    kicad_pcb_b64: Buffer.from(input.kicadPcbContent, 'utf-8').toString('base64'),
    max_steps: input.maxSteps ?? 15,
  });

  let parsed: ReasonResponseBody;
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      signal: AbortSignal.timeout(REASON_TIMEOUT_MS),
    });
    if (!response.ok) {
      log.warn({ status: response.status }, 'reasoner: non-2xx');
      return { routedPercent: 0, steps: [], usedLlm: false, warning: `HTTP ${response.status}` };
    }
    parsed = (await response.json()) as ReasonResponseBody;
  } catch (err) {
    log.warn({ err, url }, 'reasoner: fetch failed');
    return { routedPercent: 0, steps: [], usedLlm: false, warning: 'fetch failed' };
  }

  const b64 = typeof parsed.kicad_pcb_b64 === 'string' ? parsed.kicad_pcb_b64 : undefined;
  return {
    kicadPcbContent: b64 ? Buffer.from(b64, 'base64').toString('utf-8') : undefined,
    routedPercent: typeof parsed.routed_percent === 'number' ? parsed.routed_percent : 0,
    steps: Array.isArray(parsed.steps) ? parsed.steps.filter((s): s is string => typeof s === 'string') : [],
    usedLlm: parsed.used_llm === true,
    warning: typeof parsed.warning === 'string' ? parsed.warning : undefined,
  };
}
