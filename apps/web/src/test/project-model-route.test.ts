import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/**
 * `GET /api/projects/[id]/model` — le modèle 3D (GLB) du board pour le viewer
 * interactif. Ce que ces tests discriminent : l'accès (401 / 404 propriétaire /
 * 404 sans board), le corps envoyé au service (le board, en base64), le cache
 * de stockage servi avant tout export sous la clé partagée avec le pipeline,
 * le dépôt après export, l'ETag / 304, et le fail closed (503, 502 avec le
 * message du service, jamais un modèle de remplacement).
 */

const supabaseMock = vi.hoisted(() => ({ createRouteHandlerClient: vi.fn() }));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

import { GET } from '@/app/api/projects/[id]/model/route';
import { cleDuModele, cheminDuModele } from '@cirqix/agents';

const BOARD = new TextEncoder().encode('(kicad_pcb (version 20240108))');
const GLB = Uint8Array.from([0x67, 0x6c, 0x54, 0x46, 2, 0, 0, 0, 12, 0, 0, 0]);
const TOKEN = 'x'.repeat(40);

function makeClient(opts: { user?: { id: string } | null; projet?: boolean; fichier?: boolean; enCache?: Uint8Array } = {}) {
  const { user = { id: 'u1' }, projet = true, fichier = true, enCache } = opts;
  const filters: Array<[string, unknown]> = [];
  const telechargements: string[] = [];
  const depots: Array<{ chemin: string; octets: number; type: string }> = [];
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
          if (chemin.includes('/renders/')) {
            return enCache ? { data: new Blob([Buffer.from(enCache)]), error: null } : { data: null, error: { message: 'Object not found' } };
          }
          return fichier ? { data: new Blob([Buffer.from(BOARD)]), error: null } : { data: null, error: { message: 'Object not found' } };
        },
        upload: async (chemin: string, blob: Blob, options: { contentType: string }) => {
          depots.push({ chemin, octets: blob.size, type: options.contentType });
          return { data: { path: chemin }, error: null };
        },
      }),
    },
  };
  return { client, filters, telechargements, depots };
}

const ctx = { params: Promise.resolve({ id: 'p1' }) };
function requete(headers: Record<string, string> = {}) {
  return { nextUrl: new URL('http://localhost/api/projects/p1/model'), headers: new Headers(headers) } as unknown as Parameters<typeof GET>[0];
}
function serviceQuiRepond(status: number, corps: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(corps), { status, headers: { 'Content-Type': 'application/json' } }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
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
  it('401 sans session', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ user: null }).client);
    expect((await GET(requete(), ctx)).status).toBe(401);
  });
  it('404 pour le projet d’un autre compte, sans toucher au service', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ projet: false }).client);
    const fetchMock = serviceQuiRepond(200, {});
    expect((await GET(requete(), ctx)).status).toBe(404);
    expect(fetchMock).not.toHaveBeenCalled();
  });
  it('404 sans board en stockage', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ fichier: false }).client);
    serviceQuiRepond(200, {});
    expect((await GET(requete(), ctx)).status).toBe(404);
  });
});

describe('export et cache', () => {
  it('envoie le board au service, renvoie le GLB en model/gltf-binary et le dépose sous la clé partagée', async () => {
    const { client, filters, depots } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const fetchMock = serviceQuiRepond(200, { glb_b64: Buffer.from(GLB).toString('base64'), duration_ms: 2131 });
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(200);
    expect(r.headers.get('content-type')).toBe('model/gltf-binary');
    expect(r.headers.get('x-model-source')).toBe('service');
    expect(r.headers.get('x-model-duration-ms')).toBe('2131');
    expect(new Uint8Array(await r.arrayBuffer())).toEqual(GLB);
    expect(filters).toContainEqual(['user_id', 'u1']);
    const appel = fetchMock.mock.calls[0] as unknown as [string, { body: string; headers: Record<string, string> }];
    expect(appel[0]).toBe('http://kicad:8766/export/glb');
    expect(appel[1].headers['Authorization']).toBe(`Bearer ${TOKEN}`);
    expect(Buffer.from(JSON.parse(appel[1].body).kicad_pcb_b64, 'base64')).toEqual(Buffer.from(BOARD));
    const cle = cleDuModele(new Uint8Array(BOARD));
    expect(r.headers.get('etag')).toBe(`"${cle}"`);
    expect(depots).toEqual([{ chemin: `u1/p1/${cheminDuModele(cle)}`, octets: GLB.byteLength, type: 'model/gltf-binary' }]);
  });

  it('`components=0` demande la carte nue au service, sous une AUTRE clé de cache', async () => {
    const { client, depots } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const fetchMock = serviceQuiRepond(200, { glb_b64: Buffer.from(GLB).toString('base64'), duration_ms: 900, models_found: 0, models_declared: 0 });
    const req = { nextUrl: new URL('http://localhost/api/projects/p1/model?components=0'), headers: new Headers() } as unknown as Parameters<typeof GET>[0];
    const r = await GET(req, ctx);
    expect(r.status).toBe(200);
    const appel = fetchMock.mock.calls[0] as unknown as [string, { body: string }];
    expect(JSON.parse(appel[1].body).components).toBe(false);
    const cleNue = cleDuModele(new Uint8Array(BOARD), { components: false });
    expect(cleNue).not.toBe(cleDuModele(new Uint8Array(BOARD)));
    expect(r.headers.get('etag')).toBe(`"${cleNue}"`);
    expect(depots[0]?.chemin).toBe(`u1/p1/${cheminDuModele(cleNue)}`);
  });

  it('relaie le compte des modèles de composants présents sur le service', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(200, { glb_b64: Buffer.from(GLB).toString('base64'), duration_ms: 1, models_found: 0, models_declared: 9 });
    const r = await GET(requete(), ctx);
    expect(r.headers.get('x-model-components')).toBe('0/9');
    // Un service qui ne dit pas POURQUOI n'invente pas d'en-tête.
    expect(r.headers.get('x-model-components-reason')).toBeNull();
    const appel = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0] as unknown as [string, { body: string }];
    expect(JSON.parse(appel[1].body).components).toBe(true);
  });

  it('relaie POURQUOI aucun modèle n’a été trouvé', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(200, {
      glb_b64: Buffer.from(GLB).toString('base64'), duration_ms: 1,
      models_found: 0, models_declared: 26, models_reason: 'fichiers_absents',
    });
    const r = await GET(requete(), ctx);
    expect(r.headers.get('x-model-components')).toBe('0/26');
    expect(r.headers.get('x-model-components-reason')).toBe('fichiers_absents');
  });

  it('sert le modèle déjà déposé sans appeler le service', async () => {
    const enCache = Uint8Array.from([0x67, 0x6c, 0x54, 0x46, 2, 0, 0, 0, 9, 9, 9, 9]);
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient({ enCache }).client);
    const fetchMock = serviceQuiRepond(200, {});
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(200);
    expect(r.headers.get('x-model-source')).toBe('storage');
    expect(new Uint8Array(await r.arrayBuffer())).toEqual(enCache);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('304 quand l’ETag correspond, sans stockage ni service', async () => {
    const { client, telechargements } = makeClient();
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    const fetchMock = serviceQuiRepond(200, {});
    const cle = cleDuModele(new Uint8Array(BOARD));
    const r = await GET(requete({ 'if-none-match': `"${cle}"` }), ctx);
    expect(r.status).toBe(304);
    expect(telechargements).toEqual(['u1/p1/pcb.kicad_pcb']);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('fail closed', () => {
  it('503 sans configuration du service', async () => {
    delete process.env['KICAD_SERVICE_TOKEN'];
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    expect((await GET(requete(), ctx)).status).toBe(503);
  });
  it('502 avec le message du service — jamais un modèle de remplacement', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(500, { detail: 'kicad-cli pcb export glb failed (rc=1): Failed to load board' });
    const r = await GET(requete(), ctx);
    expect(r.status).toBe(502);
    expect(await r.json()).toMatchObject({ error: expect.stringContaining('Failed to load board') });
  });
  it('502 quand le service répond sans modèle', async () => {
    supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient().client);
    serviceQuiRepond(200, { glb_b64: '' });
    expect((await GET(requete(), ctx)).status).toBe(502);
  });
});
