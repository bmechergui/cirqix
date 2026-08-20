/**
 * Suivi d'un run asynchrone.
 *
 * En mode asynchrone, `POST /api/agent` répond `202 {runId}` et rend la main :
 * il n'y a plus de flux SSE à lire. La progression vit dans `pcb_run_events`,
 * que ce module relit par curseur (`GET /api/agent/runs/:runId/events?since=`).
 *
 * Deux propriétés que le SSE n'avait pas :
 *   - fermer l'onglet n'interrompt plus le run, et le rouvrir REJOUE
 *     l'historique complet — ce qui compte quand un routage dure 15 à 20 min ;
 *   - le worker n'a besoin d'aucune connexion vers le navigateur, donc aucun
 *     port publié.
 *
 * ⚠️ Un silence ne signifie PAS une panne. Un routage travaille des minutes sans
 * rien émettre : c'est le mode normal, pas un incident.
 *
 * Ce module fait de la relecture par sondage. Supabase Realtime, prévu comme
 * transport principal, viendra par-dessus — le sondage restant le repli quand la
 * souscription échoue ou que Realtime est désactivé sur le projet. Le contrat de
 * données est le même, donc l'ajout ne changera rien à l'appelant.
 */

import type { AgentSseEvent } from './agent-client';

/** Cadence tant que des événements arrivent. */
export const POLL_FAST_MS = 700;
/**
 * Cadence quand le run est silencieux. Un routage peut ne rien émettre pendant
 * plusieurs minutes ; garder la cadence rapide y ferait des centaines de
 * requêtes pour rien.
 */
export const POLL_IDLE_MS = 3_000;

/** Types que ce client sait interpréter. */
const KNOWN_KINDS = new Set([
  'token',
  'step',
  'status',
  'pcb_state',
  'reasoning',
  'error',
  'done',
]);

export interface RunEventRow {
  seq: number;
  kind: string;
  payload: Record<string, unknown>;
}

/**
 * Reconstruit un événement à partir de sa ligne.
 *
 * Renvoie `null` sur un type inconnu plutôt que de le laisser passer : une
 * version future du worker peut écrire des types que ce client ignore, et les
 * faire remonter tels quels ferait échouer le réducteur d'état sur un `type`
 * non prévu.
 */
export function rowToEvent(row: RunEventRow): AgentSseEvent | null {
  if (!KNOWN_KINDS.has(row.kind)) return null;
  return { type: row.kind, ...row.payload } as AgentSseEvent;
}

export function nextPollDelayMs(receivedCount: number): number {
  return receivedCount > 0 ? POLL_FAST_MS : POLL_IDLE_MS;
}

interface FollowRunOptions {
  runId: string;
  onEvent: (ev: AgentSseEvent) => void;
  signal?: AbortSignal;
  /** Nombre d'échecs de lecture consécutifs tolérés avant d'abandonner. */
  maxAttempts?: number;
  /** Injectable pour les tests — évite d'attendre réellement. */
  sleep?: (ms: number) => Promise<void>;
}

const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Suit un run jusqu'à son terme.
 *
 * S'arrête sur `done` ou `error` — on ne réinterroge pas un run clos — et sur
 * l'annulation du signal.
 */
export async function followRun({
  runId,
  onEvent,
  signal,
  maxAttempts = 5,
  sleep = defaultSleep,
}: FollowRunOptions): Promise<void> {
  let cursor = 0;
  let failures = 0;

  for (;;) {
    if (signal?.aborted) return;

    let payload: { events: RunEventRow[]; cursor: number; hasMore: boolean };
    try {
      const init: RequestInit = {};
      if (signal) init.signal = signal;
      const res = await fetch(
        `/api/agent/runs/${encodeURIComponent(runId)}/events?since=${cursor}`,
        init,
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      payload = (await res.json()) as typeof payload;
      failures = 0;
    } catch (err) {
      if (signal?.aborted) return;
      failures += 1;
      // Une coupure réseau passagère ne doit pas tuer le suivi d'un run qui,
      // lui, continue de tourner côté worker. On n'abandonne qu'après plusieurs
      // échecs consécutifs.
      if (failures >= maxAttempts) {
        onEvent({
          type: 'error',
          message:
            err instanceof Error
              ? `Suivi du run interrompu : ${err.message}`
              : 'Suivi du run interrompu',
        });
        return;
      }
      await sleep(POLL_IDLE_MS);
      continue;
    }

    for (const row of payload.events) {
      const ev = rowToEvent(row);
      if (!ev) continue;
      onEvent(ev);
      if (ev.type === 'done' || ev.type === 'error') return;
    }

    cursor = payload.cursor;
    if (!payload.hasMore) await sleep(nextPollDelayMs(payload.events.length));
  }
}
