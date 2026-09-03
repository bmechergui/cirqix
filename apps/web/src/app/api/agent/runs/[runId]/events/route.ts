import { NextResponse } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { logger } from '@cirqix/logger';

/**
 * Relecture du journal d'un run.
 *
 * Deux usages, une seule route :
 *   - REPLI de Supabase Realtime, quand la souscription échoue ou que Realtime
 *     est désactivé sur le projet ;
 *   - REPRISE après coupure : `?since=<seq>` rejoue ce qui a été manqué.
 *
 * C'est ce qui rend un run survivable à la fermeture de l'onglet — le point qui
 * compte le plus quand un routage complexe dure 15 à 20 minutes.
 *
 * L'isolation ne repose PAS sur cette route : `pcb_run_events` porte une
 * politique RLS `SELECT` limitée au porteur du run (migration 019), et le client
 * est créé avec le JWT de l'appelant. Un run d'autrui renvoie donc simplement
 * une liste vide, sans qu'aucun filtre applicatif n'ait à y penser.
 */

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';

const log = logger.child({ module: 'run-events' });

/** `since` est un curseur exclusif : on renvoie ce qui suit strictement. */
const Query = z.object({
  since: z.coerce.number().int().min(0).default(0),
  limit: z.coerce.number().int().min(1).max(500).default(200),
});

export async function GET(
  request: Request,
  context: { params: Promise<{ runId: string }> },
) {
  const { runId } = await context.params;

  const parsed = Query.safeParse(
    Object.fromEntries(new URL(request.url).searchParams),
  );
  if (!parsed.success) {
    return NextResponse.json({ error: 'invalid query parameters' }, { status: 400 });
  }

  const supabase = await createRouteHandlerClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ error: 'unauthorized' }, { status: 401 });
  }

  const { data, error } = await supabase
    .from('pcb_run_events')
    .select('seq, kind, payload, created_at')
    .eq('run_id', runId)
    .gt('seq', parsed.data.since)
    .order('seq', { ascending: true })
    .limit(parsed.data.limit);

  if (error) {
    log.error({ err: error, runId }, 'lecture du journal échouée');
    return NextResponse.json({ error: 'failed to read run events' }, { status: 500 });
  }

  const events = data ?? [];
  return NextResponse.json({
    events,
    // Curseur à repasser tel quel au prochain appel. Vaut `since` quand rien
    // n'est arrivé, pour qu'un client qui boucle ne reparte pas de zéro.
    cursor: events.length > 0 ? events[events.length - 1]!.seq : parsed.data.since,
    // Le client sait ainsi s'il doit rappeler immédiatement plutôt qu'attendre.
    hasMore: events.length === parsed.data.limit,
  });
}
