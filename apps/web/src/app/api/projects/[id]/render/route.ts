import { createHash } from 'node:crypto';
import { NextResponse, type NextRequest } from 'next/server';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { parseRenderQuery, serviceRenderOptions, type RenderParams } from '@/shared/lib/render-presets';

/**
 * `GET /api/projects/[id]/render?view=top|bottom|iso|…&quality=basic|high&yaw=&zoom=&w=&h=`
 *
 * Rend le board du projet en PNG par le service KiCad (`POST /render/auto`,
 * `kicad-cli pcb render`) et le renvoie tel quel en `image/png` — le viewer
 * le met dans un `<img>`. Rien n'est dessiné côté web : c'est le rendu de KiCad.
 *
 * Cache : l'ETag dérive du CONTENU du board et des paramètres. Un `<img>`
 * revalidé avec `If-None-Match` reçoit 304 sans qu'aucun rendu ne tourne ; un
 * board régénéré change d'ETag et se re-rend. Le `.kicad_pcb` est de toute
 * façon téléchargé (quelques centaines de ko) — c'est le rendu qui coûte.
 *
 * FAIL CLOSED : service non configuré → 503 ; rendu en échec → 502 avec le
 * message du service. Jamais une image de remplacement.
 */

export const maxDuration = 120;

const BUCKET = 'kicad-files';
const MIN_SERVICE_TOKEN_LENGTH = 32;
const RENDER_TIMEOUT_MS = 110_000;
const CACHE_CONTROL = 'private, max-age=600';

function etagPour(board: Uint8Array, params: RenderParams): string {
  const h = createHash('sha1');
  h.update(board);
  h.update(JSON.stringify(params));
  return `"${h.digest('hex')}"`;
}

function configurationDuService(env: NodeJS.ProcessEnv): { url: string; headers: Record<string, string> } | null {
  const url = env['KICAD_SERVICE_URL']?.trim().replace(/\/+$/, '');
  const token = env['KICAD_SERVICE_TOKEN']?.trim();
  if (!url || !token || token.length < MIN_SERVICE_TOKEN_LENGTH) return null;
  return { url, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } };
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const parsed = parseRenderQuery(req.nextUrl.searchParams);
  if (!parsed.ok) {
    return NextResponse.json({ success: false, error: parsed.error }, { status: 400 });
  }

  const { id } = await ctx.params;
  // Propriétaire ET id — la même double barrière que `pcb-state` : le chemin
  // de stockage est construit sous `${user.id}/${projectId}/`.
  const { data: projet, error } = await supabase
    .from('projects')
    .select('id')
    .eq('id', id)
    .eq('user_id', user.id)
    .single();
  if (error || !projet) {
    return NextResponse.json({ success: false, error: 'Not found' }, { status: 404 });
  }

  const service = configurationDuService(process.env);
  if (!service) {
    return NextResponse.json({ success: false, error: 'KiCad service not configured' }, { status: 503 });
  }

  const { data: fichier, error: erreurFichier } = await supabase.storage
    .from(BUCKET)
    .download(`${user.id}/${id}/pcb.kicad_pcb`);
  if (erreurFichier || !fichier) {
    return NextResponse.json({ success: false, error: 'No board to render yet' }, { status: 404 });
  }
  const board = new Uint8Array(await fichier.arrayBuffer());

  const etag = etagPour(board, parsed.params);
  if (req.headers.get('if-none-match') === etag) {
    return new NextResponse(null, { status: 304, headers: { ETag: etag, 'Cache-Control': CACHE_CONTROL } });
  }

  let reponse: Response;
  try {
    reponse = await fetch(`${service.url}/render/auto`, {
      method: 'POST',
      headers: service.headers,
      body: JSON.stringify({
        kicad_pcb_b64: Buffer.from(board).toString('base64'),
        ...serviceRenderOptions(parsed.params),
      }),
      signal: AbortSignal.timeout(RENDER_TIMEOUT_MS),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'render request failed';
    return NextResponse.json({ success: false, error: `Render unavailable: ${message}` }, { status: 502 });
  }

  if (!reponse.ok) {
    let detail = `service responded ${reponse.status}`;
    try {
      const corps = (await reponse.json()) as { detail?: unknown };
      if (typeof corps.detail === 'string') detail = corps.detail;
    } catch {
      // corps non JSON : on garde le statut
    }
    return NextResponse.json({ success: false, error: `Render failed: ${detail}` }, { status: 502 });
  }

  const corps = (await reponse.json()) as { png_b64?: unknown; duration_ms?: unknown };
  if (typeof corps.png_b64 !== 'string' || corps.png_b64.length === 0) {
    return NextResponse.json({ success: false, error: 'Render failed: service returned no image' }, { status: 502 });
  }
  const png = Buffer.from(corps.png_b64, 'base64');

  return new NextResponse(png, {
    status: 200,
    headers: {
      'Content-Type': 'image/png',
      'Content-Length': String(png.byteLength),
      'Cache-Control': CACHE_CONTROL,
      ETag: etag,
      'X-Render-Duration-Ms': String(typeof corps.duration_ms === 'number' ? corps.duration_ms : -1),
    },
  });
}
