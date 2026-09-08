/**
 * Sondage de la progression du routage.
 *
 * ⚠️ Le service MESURE depuis toujours : `_route_with_freerouting_api` relit le
 * journal de la JVM toutes les deux secondes et en tire le numéro de passe et
 * le nombre de nets non routés. Cette mesure ne sortait pas du service —
 * l'utilisateur voyait « routage en cours » pendant vingt minutes.
 *
 * ⚠️ La progression est un CONFORT D'AFFICHAGE, jamais un verdict. Aucune de
 * ses pannes ne doit interrompre un routage déjà payé : un service muet, un
 * 500, un JSON illisible se lisent tous « rien à afficher ».
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  readRoutingProgress,
  followRoutingProgress,
} from '../engines/routing-progress';

const BASE = 'http://kicad.test:8766';

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const TOKEN = 'x'.repeat(40);

beforeEach(() => {
  process.env['KICAD_SERVICE_URL'] = BASE;
  process.env['KICAD_SERVICE_TOKEN'] = TOKEN;
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete process.env['KICAD_SERVICE_URL'];
  delete process.env['KICAD_SERVICE_TOKEN'];
});

describe('lecture d une progression', () => {
  it('rend la mesure publiée par le routeur', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        connu: true,
        passe: 4,
        non_routes: 46,
        nets: 99,
        palier: 2,
        pourcentage: 54,
        mis_a_jour: 1_700_000_000,
      }),
    );
    vi.stubGlobal('fetch', fetchMock);

    const vu = await readRoutingProgress('projet-1');

    expect(vu).toEqual({ pass: 4, unrouted: 46, nets: 99, layers: 2, percent: 54 });
    expect(fetchMock).toHaveBeenCalledWith(
      `${BASE}/route/progress/projet-1`,
      expect.objectContaining({ method: 'GET' }),
    );
  });

  it('rend null quand le routeur n a encore rien publié', async () => {
    // Le sondeur interroge AVANT la première passe : sur une carte lente cela
    // dure plusieurs minutes. Ce n'est pas une panne.
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ connu: false })));
    expect(await readRoutingProgress('projet-1')).toBeNull();
  });

  it('rend null plutôt que de propager une panne du service', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));
    expect(await readRoutingProgress('projet-1')).toBeNull();
  });

  it('rend null sur une réponse non-2xx', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({}, 500)));
    expect(await readRoutingProgress('projet-1')).toBeNull();
  });

  it('rend null sur un corps illisible', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('pas du json', { status: 200 })),
    );
    expect(await readRoutingProgress('projet-1')).toBeNull();
  });

  it('rend null quand le service n est pas configuré', async () => {
    delete process.env['KICAD_SERVICE_URL'];
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    expect(await readRoutingProgress('projet-1')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('suivi pendant le routage', () => {
  it('émet chaque avancée et ignore les répétitions', async () => {
    // ⚠️ Le routeur republie à chaque sondage, même sans avoir avancé — 999
    // passes identiques ont déjà été mesurées sur stm32-100. Réémettre à
    // l'identique remplirait le journal du run sans rien apprendre au lecteur.
    const mesures = [
      { connu: true, passe: 1, non_routes: 90, nets: 99, palier: 2, pourcentage: 9 },
      { connu: true, passe: 1, non_routes: 90, nets: 99, palier: 2, pourcentage: 9 },
      { connu: true, passe: 4, non_routes: 46, nets: 99, palier: 2, pourcentage: 54 },
    ];
    let i = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() =>
        Promise.resolve(jsonResponse(mesures[Math.min(i++, mesures.length - 1)])),
      ),
    );

    const vus: unknown[] = [];
    const control = new AbortController();
    const suivi = followRoutingProgress({
      key: 'projet-1',
      onProgress: (p) => {
        vus.push(p);
        if (vus.length === 2) control.abort();
      },
      signal: control.signal,
      intervalMs: 0,
    });
    await suivi;

    expect(vus).toEqual([
      { pass: 1, unrouted: 90, nets: 99, layers: 2, percent: 9 },
      { pass: 4, unrouted: 46, nets: 99, layers: 2, percent: 54 },
    ]);
  });

  it('s arrête sur le signal sans jamais rejeter', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ connu: false })));
    const control = new AbortController();
    control.abort();
    await expect(
      followRoutingProgress({
        key: 'projet-1',
        onProgress: () => undefined,
        signal: control.signal,
        intervalMs: 0,
      }),
    ).resolves.toBeUndefined();
  });

  it('survit à un service qui tombe en cours de route', async () => {
    // Un routage de vingt minutes traverse des redémarrages de conteneur. Le
    // suivi doit reprendre, pas mourir.
    let appels = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => {
        appels += 1;
        if (appels === 1) return Promise.reject(new Error('ECONNREFUSED'));
        return Promise.resolve(
          jsonResponse({
            connu: true, passe: 2, non_routes: 10, nets: 20, palier: 2, pourcentage: 50,
          }),
        );
      }),
    );

    const vus: unknown[] = [];
    const control = new AbortController();
    await followRoutingProgress({
      key: 'projet-1',
      onProgress: (p) => {
        vus.push(p);
        control.abort();
      },
      signal: control.signal,
      intervalMs: 0,
    });

    expect(vus).toHaveLength(1);
    expect(appels).toBeGreaterThan(1);
  });

  it('n interrompt pas le suivi quand l affichage lève', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse({
          connu: true, passe: 1, non_routes: 1, nets: 2, palier: 2, pourcentage: 50,
        }),
      ),
    );
    const control = new AbortController();
    let appels = 0;
    await expect(
      followRoutingProgress({
        key: 'projet-1',
        onProgress: () => {
          appels += 1;
          if (appels >= 1) control.abort();
          throw new Error('sink en panne');
        },
        signal: control.signal,
        intervalMs: 0,
      }),
    ).resolves.toBeUndefined();
  });
});

describe('configuration incomplete', () => {
  it('rend null quand le jeton de service manque', async () => {
    // ⚠️ `buildKicadServiceHeaders` LEVE sur un jeton absent — c'est juste pour
    // un appel qui compte. Ici la mesure n'est qu'un affichage : la lever
    // ferait tomber un routage a cause de son indicateur.
    delete process.env['KICAD_SERVICE_TOKEN'];
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    expect(await readRoutingProgress('projet-1')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
