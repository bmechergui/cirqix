import { NextResponse, type NextRequest } from 'next/server';
import { createRouteHandlerClient } from '@/shared/lib/supabase-server';
import { logger } from '@cirqix/logger';
import { cleDuModele, cheminDuModele } from '@cirqix/agents';

/**
 * `GET /api/projects/[id]/model` — le modèle 3D du board (GLB, glTF binaire),
 * exporté par KiCad (`kicad-cli pcb export glb`) pour le viewer interactif :
 * carte, pistes, pastilles, zones — la géométrie réelle, à faire tourner à
 * la souris. Rien n'est dessiné côté web.
 *
 * Même cache à deux niveaux que `render` : ETag sur le contenu du board
 * (304 sans export), et stockage sous `renders/<clé>.glb` — déposé par le
 * pipeline à la livraison (`prerendus.ts`) ou par un appel précédent.
 *
 * FAIL CLOSED : service non configuré → 503 ; export en échec → 502 avec le
 * message du service. Jamais un modèle de remplacement.
 */

export const maxDuration = 120;

const BUCKET = 'kicad-files';
const MIN_SERVICE_TOKEN_LENGTH = 32;
const EXPORT_TIMEOUT_MS = 110_000;
const CACHE_CONTROL = 'private, max-age=600';

function configurationDuService(env: NodeJS.ProcessEnv): { url: string; headers: Record<string, string> } | null {
  const url = env['KICAD_SERVICE_URL']?.trim().replace(/\/+$/, '');
  const token = env['KICAD_SERVICE_TOKEN']?.trim();
  if (!url || !token || token.length < MIN_SERVICE_TOKEN_LENGTH) return null;
  return { url, headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` } };
}

function reponseGlb(glb: Buffer, etag: string, source: 'storage' | 'service', durationMs: number): NextResponse {
  return new NextResponse(new Uint8Array(glb), {
    status: 200,
    headers: {
      'Content-Type': 'model/gltf-binary',
      'Content-Length': String(glb.byteLength),
      'Cache-Control': CACHE_CONTROL,
      ETag: etag,
      'X-Model-Source': source,
      'X-Model-Duration-Ms': String(durationMs),
    },
  });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const supabase = await createRouteHandlerClient();
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { id } = await ctx.params;
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
    return NextResponse.json({ success: false, error: 'No board to export yet' }, { status: 404 });
  }
  const board = new Uint8Array(await fichier.arrayBuffer());

  const cle = cleDuModele(board);
  const etag = `"${cle}"`;
  if (req.headers.get('if-none-match') === etag) {
    return new NextResponse(null, { status: 304, headers: { ETag: etag, 'Cache-Control': CACHE_CONTROL } });
  }

  const cheminCache = `${user.id}/${id}/${cheminDuModele(cle)}`;
  const { data: enCache } = await supabase.storage.from(BUCKET).download(cheminCache);
  if (enCache) {
    const glb = Buffer.from(await enCache.arrayBuffer());
    if (glb.byteLength > 0) return reponseGlb(glb, etag, 'storage', 0);
  }

  let reponse: Response;
  try {
    reponse = await fetch(`${service.url}/export/glb`, {
      method: 'POST',
      headers: service.headers,
      body: JSON.stringify({ kicad_pcb_b64: Buffer.from(board).toString('base64') }),
      signal: AbortSignal.timeout(EXPORT_TIMEOUT_MS),
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'export request failed';
    return NextResponse.json({ success: false, error: `3D model unavailable: ${message}` }, { status: 502 });
  }

  if (!reponse.ok) {
    let detail = `service responded ${reponse.status}`;
    try {
      const corps = (await reponse.json()) as { detail?: unknown };
      if (typeof corps.detail === 'string') detail = corps.detail;
    } catch {
      // corps non JSON : on garde le statut
    }
    return NextResponse.json({ success: false, error: `3D export failed: ${detail}` }, { status: 502 });
  }

  const corps = (await reponse.json()) as { glb_b64?: unknown; duration_ms?: unknown };
  if (typeof corps.glb_b64 !== 'string' || corps.glb_b64.length === 0) {
    return NextResponse.json({ success: false, error: '3D export failed: service returned no model' }, { status: 502 });
  }
  const glb = Buffer.from(corps.glb_b64, 'base64');

  const { error: erreurDepot } = await supabase.storage
    .from(BUCKET)
    .upload(cheminCache, new Blob([new Uint8Array(glb)], { type: 'model/gltf-binary' }), { upsert: true, contentType: 'model/gltf-binary' });
  if (erreurDepot) {
    logger.child({ module: 'model-route' }).warn({ err: erreurDepot, cheminCache }, 'dépôt du modèle en cache échoué');
  }

  return reponseGlb(glb, etag, 'service', typeof corps.duration_ms === 'number' ? corps.duration_ms : -1);
}
