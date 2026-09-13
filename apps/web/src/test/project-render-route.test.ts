import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/**
 * `GET /api/projects/[id]/render` — le PNG / la 3D d'un board, rendus par KiCad.
 *
 * Ce que ces tests discriminent :
 *  - l'accès : 401 sans session, 404 pour un projet d'un autre compte, 404
 *    sans board en stockage ;
 *  - la traduction : la vue demandée arrive au service sous les BONNES options
 *    `kicad-cli` (side / rotate / perspective) — une vue acceptée puis rendue
 *    « top » quoi qu'il arrive passerait tous les tests d'affichage ;
 *  - la sortie : les octets du service sont renvoyés tels quels en image/png ;
 *  - le cache : même board + mêmes paramètres → 304 sans appel au service ;
 *  - fail closed : service absent 503, service en échec 502, jamais une image.
 */

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { GET } from '@/app/api/projects/[id]/render/route';
import { parseRenderQuery, renderQueryString, serviceRenderOptions, appliquerYaw } from '@/shared/lib/render-presets';

const BOARD = new TextEncoder().encode('(kicad_pcb (version 20240108))');
const PNG = Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);
const TOKEN = 'x'.repeat(40);

function makeClient(opts: { user?: { id: string } | null; projet?: boolean; fichier?: boolean } = {}) {
  const { user = { id: 'u1' }, projet = true, fichier = true } = opts;
  const filters: Array<[string, unknown]> = [];
  const telechargements: string[] = [];
  const chain: Record<string, unknown> = {};
  chain['eq'] = (col: string, val: unknown) => { filters.push([col, val]); return chain; };
  chain['single'] = async () => (projet ? { data: { id: 'p1' }, error: null } : { data: null, error: { message: 'no row' } });
  const client = {
    auth: { getUser: async () => ({ data: { user } }) },
    from: () => ({ select: () => chain }),
    storage: {
      from: () => ({
        download: async (chemin: string) => {
          telechargements.push(chemin);
          return fichier
            ? { data: new Blob([BOARD]), error: null }
            : { data: null, error: { message: 'Object not found' } };
        },
      }),
    },
  };
  return { client, filters, telechargements };
}

function requete(query = 'view=top', headers: Record<string, string> = {}) {
  const url = new URL(`http://localhost/api/projects/p1/render?${query}`);
  return {
    nextUrl: url,
    headers: new Headers(headers),
  } as unknown as Parameters<typeof GET>[0];
}

const ctx = { params: Promise.resolve({ id: 'p1' }) };

function serviceQuiRepond(status: number, corps: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(corps), { status, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

function corpsEnvoye(fetchMock: ReturnType<typeof vi.fn>): Record<string, unknown> {
  const appel = fetchMock.mock.calls[0] as unknown as [string, { body: string }];
  return JSON.parse(appel[1].body) as Record<string, unknown>;
}

beforeEach(() => {
  vi.clearAllMocks();
  process.env['KICAD_SERVICE_URL'] = 'http://kicad:8766/';
  process.env['KICAD_SERVICE_TOKEN'] = TOKEN;
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env['KICAD_SERVICE_URL'];
  delete process.env['KICAD_SERVICE_TOKEN'];
});

describe('accès', () => {
  it('refuse un appel non authentifié', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ user: null }).client);
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(401);
  });

  it('filtre sur le propriétaire et l’id, et télécharge sous `${user}/${projet}/`', async () => {
    const { client, filters, telechargements } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const fetchMock = serviceQuiRepond(200, { png_b64: Buffer.from(PNG).toString('base64'), duration_ms: 12 });
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(200);
    expect(filters).toContainEqual(['user_id', 'u1']);
    expect(filters).toContainEqual(['id', 'p1']);
    expect(telechargements).toEqual(['u1/p1/pcb.kicad_pcb']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('404 pour un projet qui n’appartient pas au compte', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ projet: false }).client);
    const fetchMock = serviceQuiRepond(200, {});
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('404 quand aucun board n’est en stockage', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ fichier: false }).client);
    const fetchMock = serviceQuiRepond(200, {});
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(404);
    expect(await r.json()).toMatchObject({ error: 'No board to render yet' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('400 pour une vue inconnue, sans toucher au stockage ni au service', async () => {
    const { client, telechargements } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const fetchMock = serviceQuiRepond(200, {});
    const r = await GET(requete('view=diagonal'), ctx);
    expect(r.status).toBe(400);
    expect(telechargements).toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('la vue demandée arrive au service sous les bonnes options kicad-cli', () => {
  it.each([
    ['view=top', { side: 'top', rotate: null, perspective: false }],
    ['view=bottom', { side: 'bottom', rotate: null, perspective: false }],
    ['view=iso', { side: 'top', rotate: '-45,0,45', perspective: true }],
    ['view=iso&yaw=90', { side: 'top', rotate: '-45,0,135', perspective: true }],
    ['view=front', { side: 'front', rotate: null, perspective: true }],
  ])('%s', async (query, attendu) => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    const fetchMock = serviceQuiRepond(200, { png_b64: Buffer.from(PNG).toString('base64') });
    await GET(requete(query), ctx);
    const corps = corpsEnvoye(fetchMock);
    expect(corps).toMatchObject(attendu);
    expect(Buffer.from(corps['kicad_pcb_b64'] as string, 'base64')).toEqual(Buffer.from(BOARD));
    const appel = fetchMock.mock.calls[0] as unknown as [string, { headers: Record<string, string> }];
    expect(appel[0]).toBe('http://kicad:8766/render/auto');
    expect(appel[1].headers['Authorization']).toBe(`Bearer ${TOKEN}`);
  });

  it('quality=high et zoom sont transmis', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    const fetchMock = serviceQuiRepond(200, { png_b64: Buffer.from(PNG).toString('base64') });
    await GET(requete('view=top&quality=high&zoom=1.5&w=800&h=600'), ctx);
    expect(corpsEnvoye(fetchMock)).toMatchObject({ quality: 'high', zoom: 1.5, width: 800, height: 600 });
  });
});

describe('sortie et cache', () => {
  it('renvoie les octets du service en image/png avec un ETag', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(200, { png_b64: Buffer.from(PNG).toString('base64'), duration_ms: 42 });
    const r = await GET(requete('view=iso'), ctx);
    expect(r.status).toBe(200);
    expect(r.headers.get('content-type')).toBe('image/png');
    expect(r.headers.get('x-render-duration-ms')).toBe('42');
    expect(r.headers.get('etag')).toMatch(/^"[0-9a-f]{40}"$/);
    expect(new Uint8Array(await r.arrayBuffer())).toEqual(PNG);
  });

  it('304 sans appel au service quand l’ETag correspond ; un autre paramètre change l’ETag', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    const fetchMock = serviceQuiRepond(200, { png_b64: Buffer.from(PNG).toString('base64') });
    const premier = await GET(requete('view=iso'), ctx);
    const etag = premier.headers.get('etag') as string;

    const revalide = await GET(requete('view=iso', { 'if-none-match': etag }), ctx);
    expect(revalide.status).toBe(304);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const autreVue = await GET(requete('view=bottom', { 'if-none-match': etag }), ctx);
    expect(autreVue.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe('fail closed', () => {
  it('503 quand le service n’est pas configuré', async () => {
    delete process.env['KICAD_SERVICE_TOKEN'];
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(503);
  });

  it('502 avec le message du service quand le rendu échoue — jamais une image', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(500, { detail: 'kicad-cli pcb render failed (rc=1): Failed to load board' });
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(502);
    expect(r.headers.get('content-type')).toContain('application/json');
    expect(await r.json()).toMatchObject({ error: expect.stringContaining('Failed to load board') });
  });

  it('502 quand le service répond 200 sans image', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(200, { png_b64: '' });
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(502);
  });

  it('502 quand le service est injoignable', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('fetch failed'); }));
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(502);
  });
});

describe('render-presets — la table et son inverse', () => {
  it('parse et sérialise sans perte', () => {
    const p = parseRenderQuery(new URLSearchParams('view=iso&quality=high&yaw=30&zoom=1.5&w=800&h=600'));
    expect(p.ok).toBe(true);
    if (!p.ok) return;
    expect(p.params).toEqual({ view: 'iso', quality: 'high', yaw: 30, zoom: 1.5, width: 800, height: 600 });
    expect(parseRenderQuery(new URLSearchParams(renderQueryString(p.params)))).toEqual(p);
  });

  it('refuse ce qui est hors bornes', () => {
    expect(parseRenderQuery(new URLSearchParams('zoom=100')).ok).toBe(false);
    expect(parseRenderQuery(new URLSearchParams('yaw=abc')).ok).toBe(false);
    expect(parseRenderQuery(new URLSearchParams('quality=ultra')).ok).toBe(false);
    expect(parseRenderQuery(new URLSearchParams('w=10')).ok).toBe(false);
  });

  it('le yaw tourne autour de Z et reste dans [0, 360)', () => {
    expect(appliquerYaw('-45,0,45', 90)).toBe('-45,0,135');
    expect(appliquerYaw('-45,0,45', -90)).toBe('-45,0,315');
    expect(serviceRenderOptions({ view: 'top', quality: 'basic', yaw: 90, zoom: 1, width: 10, height: 10 }).rotate).toBeNull();
  });
});
