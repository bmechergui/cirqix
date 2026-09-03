/**
 * Souscription Realtime au journal d'un run (`pcb_run_events`).
 *
 * La frontière de sécurité n'est PAS le filtre `run_id=eq.` : n'importe qui
 * peut composer un channel. RLS `pcb_run_events_select_own` (migration 019)
 * refuse les lignes d'autrui. Le filtre n'existe que pour ne pas recevoir
 * le journal de tous les runs du même utilisateur.
 *
 * Un échec (pas de credentials, `runId` invalide, channel en erreur, timeout)
 * rend `null` : `followRun` bascule sur le sondage, sans bloquer le suivi.
 */

import { z } from 'zod';
import { createSupabaseBrowserClient } from '@/shared/lib/supabase-browser';

export interface RealtimeRunRow {
  seq: number;
  kind: string;
  payload: Record<string, unknown>;
}

export interface SubscribeToRunEventsArgs {
  runId: string;
  onInsert: (row: RealtimeRunRow) => void;
  onLost: () => void;
  signal?: AbortSignal;
}

export interface RunSubscription {
  unsubscribe: () => void;
}

/** Au-delà, Realtime est considéré indisponible et le sondage reprend. */
export const SUBSCRIBE_TIMEOUT_MS = 2_000;

const RunId = z.string().uuid();

function asPayload(value: unknown): Record<string, unknown> {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

export function rowFromRealtime(value: unknown): RealtimeRunRow | null {
  if (!value || typeof value !== 'object') return null;
  const rec = value as Record<string, unknown>;
  const seq = typeof rec['seq'] === 'number' ? rec['seq'] : Number(rec['seq']);
  const kind = rec['kind'];
  if (!Number.isFinite(seq) || typeof kind !== 'string') return null;
  return { seq, kind, payload: asPayload(rec['payload']) };
}

export async function subscribeToRunEvents({
  runId,
  onInsert,
  onLost,
  signal,
}: SubscribeToRunEventsArgs): Promise<RunSubscription | null> {
  if (signal?.aborted) return null;

  const parsedId = RunId.safeParse(runId);
  if (!parsedId.success) return null;

  const url = process.env['NEXT_PUBLIC_SUPABASE_URL'];
  const key = process.env['NEXT_PUBLIC_SUPABASE_ANON_KEY'];
  if (!url || !key) return null;

  const supabase = createSupabaseBrowserClient();

  return new Promise((resolve) => {
    let settled = false;
    let live = false;

    const channel = supabase
      .channel(`pcb-run-events:${parsedId.data}`)
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'pcb_run_events',
          filter: `run_id=eq.${parsedId.data}`,
        },
        (payload) => {
          const row = rowFromRealtime(payload.new);
          if (row) onInsert(row);
        },
      );

    const finishUnavailable = (): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      void supabase.removeChannel(channel);
      resolve(null);
    };

    const timer = setTimeout(finishUnavailable, SUBSCRIBE_TIMEOUT_MS);

    channel.subscribe((status) => {
      if (status === 'SUBSCRIBED') {
        if (settled) return;
        settled = true;
        live = true;
        clearTimeout(timer);
        resolve({
          unsubscribe: () => {
            live = false;
            void supabase.removeChannel(channel);
          },
        });
        return;
      }
      if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
        if (!live) {
          finishUnavailable();
          return;
        }
        live = false;
        onLost();
      }
    });

    signal?.addEventListener(
      'abort',
      () => {
        live = false;
        void supabase.removeChannel(channel);
      },
      { once: true },
    );
  });
}
