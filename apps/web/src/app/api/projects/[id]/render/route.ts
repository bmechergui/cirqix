import { NextResponse, type NextRequest } from 'next/server';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { logger } from '@cirqix/logger';
import { cleDeRendu, cheminDuRendu } from '@cirqix/agents';
import { parseRenderQuery, serviceRenderOptions } from '@/shared/lib/render-presets';

/**
 * `GET /api/projects/[id]/render?view=top|bottom|iso|…&quality=basic|high&yaw=&zoom=&w=&h=`
 *
 * Rend le board du projet en PNG par le service KiCad (`POST /render/auto`,
 * `kicad-cli pcb render`) et le renvoie tel quel en `image/png` — le viewer
 * le met dans un `<img>`. Rien n'est dessiné côté web : c'est le rendu de KiCad.
 *
 * Cache, à deux niveaux, sur la même clé (`cleDeRendu` : contenu du board +
 * paramètres, partagée avec le pipeline) :
 *  - l'ETag : un `<img>` revalidé avec `If-None-Match` reçoit 304 sans rien
 *    rendre ;
 *  - le stockage : un rendu déjà déposé sous `renders/<clé>.png` — par le
 *    pipeline à la livraison (`prerendus.ts`) ou par un appel précédent — est
 *    servi tel quel. Sinon on rend, puis on dépose pour la fois suivante.
 * Un board régénéré change de clé : jamais une image périmée.
 *
 * FAIL CLOSED : service non configuré → 503 ; rendu en échec → 502 avec le
 * message du service. Jamais une image de remplacement.
 */

export const maxDuration = 120;

const BUCKET = 'kicad-files';
const MIN_SERVICE_TOKEN_LENGTH = 32;
const RENDER_TIMEOUT_MS = 110_000;
const CACHE_CONTROL = 'private, max-age=600';

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

  const cle = cleDeRendu(board, parsed.params);
  const etag = `"${cle}"`;
  if (req.headers.get('if-none-match') === etag) {
    return new NextResponse(null, { status: 304, headers: { ETag: etag, 'Cache-Control': CACHE_CONTROL } });
  }

  const cheminCache = `${user.id}/${id}/${cheminDuRendu(cle)}`;
  const { data: enCache } = await supabase.storage.from(BUCKET).download(cheminCache);
  if (enCache) {
    const png = Buffer.from(await enCache.arrayBuffer());
    if (png.byteLength > 0) return reponsePng(png, etag, 0, 'storage');
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

  // Dépôt pour la fois suivante — best-effort, l'image part sans attendre.
  const { error: erreurDepot } = await supabase.storage
    .from(BUCKET)
    .upload(cheminCache, new Blob([png], { type: 'image/png' }), { upsert: true, contentType: 'image/png' });
  if (erreurDepot) {
    logger.child({ module: 'render-route' }).warn({ err: erreurDepot, cheminCache }, 'dépôt du rendu en cache échoué');
  }

  return reponsePng(png, etag, typeof corps.duration_ms === 'number' ? corps.duration_ms : -1, 'service');
}

function reponsePng(png: Buffer, etag: string, durationMs: number, source: 'storage' | 'service'): NextResponse {
  return new NextResponse(new Uint8Array(png), {
    status: 200,
    headers: {
      'Content-Type': 'image/png',
      'Content-Length': String(png.byteLength),
      'Cache-Control': CACHE_CONTROL,
      ETag: etag,
      'X-Render-Duration-Ms': String(durationMs),
      'X-Render-Source': source,
    },
  });
}
