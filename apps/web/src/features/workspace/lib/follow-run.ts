/**
 * Suivi d'un run asynchrone.
 *
 * En mode asynchrone, `POST /api/agent` répond `202 {runId}` et rend la main :
 * il n'y a plus de flux SSE à lire. La progression vit dans `pcb_run_events`.
 *
 * Transport principal : Supabase Realtime (INSERT). Repli : relecture HTTP
 * par curseur (`GET /api/agent/runs/:runId/events?since=`), aussi utilisée
 * en catch-up au branchement — les lignes arrivées avant `SUBSCRIBED` ne
 * doivent pas disparaître.
 *
 * Le sondage continue à cadence lente même si Realtime est `SUBSCRIBED` :
 * une souscription « ok » sans événement (publication absente, RLS muette)
 * ressemble à un routage silencieux de 15 min. `seen` ignore les doublons.
 *
 * ⚠️ Un silence ne signifie PAS une panne. Un routage travaille des minutes sans
 * rien émettre : c'est le mode normal, pas un incident.
 */

import type { AgentSseEvent } from './agent-client';
import { rowFromRealtime, subscribeToRunEvents } from './follow-run-realtime';

/** Cadence tant que des événements arrivent. */
export const POLL_FAST_MS = 700;
/**
 * Cadence quand le run est silencieux. Un routage travaille des minutes sans
 * rien émettre ; garder la cadence rapide y ferait des centaines de
 * requêtes pour rien.
 */
export const POLL_IDLE_MS = 3_000;

const KNOWN_KINDS = new Set([
  'token',
  'step',
  'progress',
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

export interface RunSubscription {
  unsubscribe: () => void;
}

/**
 * Branchement live. `null` = Realtime indisponible → sondage seul.
 * Injectable : les tests ne parlent pas à une socket.
 */
export type SubscribeToRun = (args: {
  runId: string;
  onInsert: (row: RunEventRow) => void;
  onLost: () => void;
  signal?: AbortSignal;
}) => Promise<RunSubscription | null>;

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
  const { type: _ignored, ...rest } = row.payload;
  return { type: row.kind, ...rest } as AgentSseEvent;
}

export function nextPollDelayMs(receivedCount: number): number {
  return receivedCount > 0 ? POLL_FAST_MS : POLL_IDLE_MS;
}

interface FollowRunOptions {
  runId: string;
  onEvent: (ev: AgentSseEvent) => void;
  signal?: AbortSignal;
  maxAttempts?: number;
  sleep?: (ms: number) => Promise<void>;
  subscribe?: SubscribeToRun;
}

const defaultSleep = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, ms));

interface EventsPage {
  events: unknown[];
  cursor: number;
  hasMore: boolean;
}

function parsePage(raw: unknown): EventsPage {
  if (!raw || typeof raw !== 'object') {
    return { events: [], cursor: 0, hasMore: false };
  }
  const rec = raw as Record<string, unknown>;
  const events = Array.isArray(rec['events']) ? rec['events'] : [];
  const cursor = Number(rec['cursor']);
  return {
    events,
    cursor: Number.isFinite(cursor) ? cursor : 0,
    hasMore: rec['hasMore'] === true,
  };
}

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
  subscribe = subscribeToRunEvents,
}: FollowRunOptions): Promise<void> {
  const seen = new Set<number>();
  let cursor = 0;
  let closed = false;
  let wake: (() => void) | undefined;
  /** Tampon des INSERT live pendant le catch-up HTTP, pour préserver l'ordre. */
  let buffer: RunEventRow[] | null = [];

  function deliver(row: RunEventRow): void {
    if (seen.has(row.seq)) return;
    seen.add(row.seq);
    if (row.seq > cursor) cursor = row.seq;
    const ev = rowToEvent(row);
    if (!ev) return;
    onEvent(ev);
    if (ev.type === 'done' || ev.type === 'error') {
      closed = true;
      wake?.();
    }
  }

  function ingest(row: RunEventRow): void {
    if (buffer) {
      buffer.push(row);
      return;
    }
    deliver(row);
  }

  function flushBuffer(): void {
    const queued = buffer ?? [];
    buffer = null;
    queued.sort((a, b) => a.seq - b.seq);
    for (const row of queued) deliver(row);
  }

  const subscribeArgs: Parameters<SubscribeToRun>[0] = {
    runId,
    onInsert: ingest,
    onLost: () => {
      wake?.();
    },
  };
  if (signal) subscribeArgs.signal = signal;
  const subPromise: Promise<RunSubscription | null> = subscribe(subscribeArgs).catch(
    () => null,
  );

  if (signal?.aborted) closed = true;
  else if (signal) {
    signal.addEventListener(
      'abort',
      () => {
        closed = true;
        wake?.();
      },
      { once: true },
    );
  }

  let failures = 0;

  async function pull(): Promise<EventsPage> {
    const init: RequestInit = {};
    if (signal) init.signal = signal;
    const res = await fetch(
      `/api/agent/runs/${encodeURIComponent(runId)}/events?since=${cursor}`,
      init,
    );
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const page = parsePage(await res.json());
    for (const raw of page.events) {
      const row = rowFromRealtime(raw);
      if (row) deliver(row);
    }
    if (page.cursor > cursor) cursor = page.cursor;
    return page;
  }

  function interruptMessage(err: unknown): string {
    return err instanceof Error
      ? `Suivi du run interrompu : ${err.message}`
      : 'Suivi du run interrompu';
  }

  async function catchUpOrFail(): Promise<boolean> {
    try {
      for (;;) {
        if (closed || signal?.aborted) return true;
        const page = await pull();
        failures = 0;
        if (closed || !page.hasMore) return true;
      }
    } catch (err) {
      if (signal?.aborted) return false;
      failures += 1;
      if (failures >= maxAttempts) {
        onEvent({ type: 'error', message: interruptMessage(err) });
        closed = true;
        return false;
      }
      await sleep(POLL_IDLE_MS);
      return catchUpOrFail();
    }
  }

  async function sleepUntilClosed(ms: number): Promise<void> {
    if (closed || signal?.aborted) return;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, ms);
      wake = () => {
        clearTimeout(timer);
        resolve();
      };
    });
    wake = undefined;
  }

  try {
    const firstOk = await catchUpOrFail();
    if (!firstOk || signal?.aborted) return;

    // La souscription a tourné pendant le catch-up : ses INSERT sont dans
    // `buffer`. On les fusionne après le HTTP pour qu'un `done` live ne
    // fasse pas jeter les lignes plus anciennes encore en vol.
    await subPromise;
    flushBuffer();
    if (closed || signal?.aborted) return;

    for (;;) {
      if (signal?.aborted || closed) return;
      try {
        const page = await pull();
        failures = 0;
        if (closed) return;
        if (!page.hasMore) await sleepUntilClosed(nextPollDelayMs(page.events.length));
      } catch (err) {
        if (signal?.aborted) return;
        failures += 1;
        if (failures >= maxAttempts) {
          onEvent({ type: 'error', message: interruptMessage(err) });
          return;
        }
        await sleepUntilClosed(POLL_IDLE_MS);
      }
    }
  } finally {
    (await subPromise)?.unsubscribe();
  }
}
