import { NextResponse, type NextRequest } from 'next/server';
import { z } from 'zod';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { logger } from '@cirqix/logger';

export const dynamic = 'force-dynamic';

/** Nombre de messages rendus : les plus récents, remis dans l'ordre de lecture. */
const HISTORY_LIMIT = 200;

const projectIdSchema = z.string().uuid();

/**
 * Historique de discussion d'un projet (migration 026).
 *
 * Lecture seule : les messages sont écrits par le serveur (route agent, worker),
 * jamais par le client.
 */
export async function GET(
  _req: NextRequest,
  ctx: { params: Promise<{ id: string }> },
) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await ctx.params;
  const parsed = projectIdSchema.safeParse(id);
  if (!parsed.success) {
    return NextResponse.json({ success: false, error: 'Invalid project id' }, { status: 400 });
  }

  // `.eq('user_id', …)` en plus de la RLS : deux barrières, comme `pcb-state`.
  const { data, error } = await supabase
    .from('project_messages')
    .select('id, role, content, created_at')
    .eq('project_id', parsed.data)
    .eq('user_id', user.id)
    .order('created_at', { ascending: false })
    .limit(HISTORY_LIMIT);

  if (error || !data) {
    // Une erreur n'est pas un historique vide : l'afficher vide laisserait
    // croire que la conversation a été perdue.
    logger.child({ module: 'project-messages-route' }).error(
      { err: error, projectId: parsed.data },
      'lecture de l historique échouée',
    );
    return NextResponse.json({ success: false, error: 'Could not load messages' }, { status: 500 });
  }

  const messages = [...data].reverse();
  return NextResponse.json({ success: true, data: { messages } });
}
