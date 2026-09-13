import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/**
 * Pré-rendus à la livraison — ce que ces tests discriminent :
 *  - les vues de `PRERENDUS` sont rendues avec les BONNES options kicad-cli
 *    (iso = perspective + rotation) et déposées sous la clé que la route web
 *    recalcule — une clé différente rendrait le cache aveugle ;
 *  - un rendu en échec n'interrompt rien : les autres vues sont déposées, la
 *    fonction ne lève pas ;
 *  - un porteur sans `uploadRender` ne rend rien du tout (pas d'appel inutile).
 */
vi.hoisted(() => { process.env['LOG_LEVEL'] = 'silent'; });

import { prerendre } from '../pipeline/prerendus';
import { PRERENDUS, cleDeRendu, cheminDuRendu } from '../pipeline/render-cache';
import type { PipelineStore } from '../pipeline/store';

const BOARD = '(kicad_pcb (version 20240108))';
const TOKEN = 'x'.repeat(40);
const PNG = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 1, 2, 3]);

function faussePorteuse(): PipelineStore & { rendus: Array<{ cle: string; png: Uint8Array }> } {
  const rendus: Array<{ cle: string; png: Uint8Array }> = [];
  return {
    rendus,
    uploadArtifact: async () => ({}),
    persistProgress: async () => undefined,
    finalizeSuccess: async () => undefined,
    uploadRender: async (cle, png) => { rendus.push({ cle, png }); },
  };
}

function corpsEnvoyes(fetchMock: ReturnType<typeof vi.fn>): Array<Record<string, unknown>> {
  return fetchMock.mock.calls.map((c) => JSON.parse(((c as unknown[])[1] as { body: string }).body) as Record<string, unknown>);
}

beforeEach(() => {
  process.env['KICAD_SERVICE_URL'] = 'http://kicad:8766';
  process.env['KICAD_SERVICE_TOKEN'] = TOKEN;
});
afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env['KICAD_SERVICE_URL'];
  delete process.env['KICAD_SERVICE_TOKEN'];
});

describe('prerendre', () => {
  it('rend top et iso avec les options kicad-cli attendues et les dépose sous la clé partagée', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ png_b64: PNG.toString('base64') }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const store = faussePorteuse();

    expect(await prerendre(store, BOARD)).toBe(2);

    const corps = corpsEnvoyes(fetchMock);
    expect(corps[0]).toMatchObject({ side: 'top', rotate: null, perspective: false, quality: 'basic' });
    expect(corps[1]).toMatchObject({ side: 'top', rotate: '-45,0,45', perspective: true, quality: 'basic' });
    expect(Buffer.from(corps[0]!['kicad_pcb_b64'] as string, 'base64').toString()).toBe(BOARD);

    const board = new Uint8Array(Buffer.from(BOARD, 'utf-8'));
    expect(store.rendus.map((r) => r.cle)).toEqual(PRERENDUS.map((p) => cleDeRendu(board, p)));
    expect(Buffer.from(store.rendus[0]!.png)).toEqual(PNG);
    expect(cheminDuRendu(store.rendus[0]!.cle)).toMatch(/^renders\/[0-9a-f]{40}\.png$/);
  });

  it('un rendu en échec n’empêche ni les autres ni le retour', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: 'Failed to load board' }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ png_b64: PNG.toString('base64') }), { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const store = faussePorteuse();
    expect(await prerendre(store, BOARD)).toBe(1);
    expect(store.rendus).toHaveLength(1);
  });

  it('sans service configuré, rien n’est déposé et rien ne lève', async () => {
    delete process.env['KICAD_SERVICE_URL'];
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const store = faussePorteuse();
    expect(await prerendre(store, BOARD)).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('un porteur sans uploadRender ne déclenche aucun rendu', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const store: PipelineStore = { uploadArtifact: async () => ({}), persistProgress: async () => undefined, finalizeSuccess: async () => undefined };
    expect(await prerendre(store, BOARD)).toBe(0);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('cleDeRendu — la clé ne dépend que du board et des paramètres', () => {
  it('change avec le board et avec chaque paramètre, jamais avec l’ordre d’écriture', () => {
    const a = new Uint8Array([1, 2, 3]);
    const p = { view: 'top', quality: 'basic' as const, yaw: 0, zoom: 1, width: 1600, height: 900 };
    expect(cleDeRendu(a, p)).toBe(cleDeRendu(a, { height: 900, width: 1600, zoom: 1, yaw: 0, quality: 'basic', view: 'top' }));
    expect(cleDeRendu(a, p)).not.toBe(cleDeRendu(new Uint8Array([1, 2, 4]), p));
    expect(cleDeRendu(a, p)).not.toBe(cleDeRendu(a, { ...p, yaw: 30 }));
    expect(cleDeRendu(a, p)).not.toBe(cleDeRendu(a, { ...p, quality: 'high' }));
  });
});
