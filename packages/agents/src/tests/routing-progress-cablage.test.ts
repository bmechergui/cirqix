/**
 * Le câblage de la progression : la clé part-elle, et sans jamais nuire ?
 *
 * ⚠️ Un mécanisme correct que personne n'appelle est indistinguable d'un
 * mécanisme absent. C'est ce qui a masqué pendant des semaines le fait que le
 * Géomètre CMA-ES ne tournait jamais en production, et ce qui a fait croire que
 * le Niveau 2 de Freerouting servait alors qu'il n'avait jamais répondu.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { progressKeyFor } from '../engines/routing-progress';

// ⚠️ `runRealRouting` n'appelle pas `fetch` : il passe par `longCallFetch`,
// dont la raison d'être est de désarmer les échéances d'undici sur un routage
// de vingt minutes. Stuber `fetch` ne l'intercepterait pas.
const transport = { longCallFetch: vi.fn() };
vi.mock('../engines/long-call-transport', () => transport);

const BASE = 'http://kicad.test:8766';
const TOKEN = 'x'.repeat(40);

beforeEach(() => {
  process.env['KICAD_SERVICE_URL'] = BASE;
  process.env['KICAD_SERVICE_TOKEN'] = TOKEN;
});

afterEach(() => {
  transport.longCallFetch.mockReset();
  vi.unstubAllGlobals();
  vi.resetModules();
  delete process.env['KICAD_SERVICE_URL'];
  delete process.env['KICAD_SERVICE_TOKEN'];
});

describe('la clé de progression ne peut pas nuire au routage', () => {
  it('accepte un identifiant de projet ordinaire', () => {
    expect(progressKeyFor('7c3f1a2b-9d84-4e21-8f0a-51b6c7d2e934')).toBe(
      '7c3f1a2b-9d84-4e21-8f0a-51b6c7d2e934',
    );
  });

  it('renonce plutôt que d envoyer une clé que le service refuserait', () => {
    // ⚠️ Le service valide la clé et répond 422 : une clé exotique ferait
    // échouer LE ROUTAGE ENTIER pour un simple indicateur d'avancement. Perdre
    // l'affichage est acceptable ; perdre la carte ne l'est pas.
    expect(progressKeyFor('projet/../../etc')).toBeUndefined();
    expect(progressKeyFor('avec espace')).toBeUndefined();
    expect(progressKeyFor('')).toBeUndefined();
    expect(progressKeyFor('x'.repeat(200))).toBeUndefined();
  });
});

describe('la clé voyage jusqu au service', () => {
  it('runRealRouting la place dans le corps de la requête', async () => {
    transport.longCallFetch.mockResolvedValue(
      new Response(JSON.stringify({ routed_percent: 100, layers: 2 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const { runRealRouting } = await import('../engines/routing-service.js');
    await runRealRouting({
      kicadPcbContent: '(kicad_pcb)',
      layers: 2,
      progressKey: 'projet-1',
    });

    const appel = transport.longCallFetch.mock.calls[0];
    const corps = JSON.parse((appel?.[1] as { body: string }).body);
    expect(corps.progress_key).toBe('projet-1');
  });

  it('n envoie aucune clé quand l appelant n en fournit pas', async () => {
    // Tout appelant existant doit router exactement comme avant.
    transport.longCallFetch.mockResolvedValue(
      new Response(JSON.stringify({ routed_percent: 100, layers: 2 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    );

    const { runRealRouting } = await import('../engines/routing-service.js');
    await runRealRouting({ kicadPcbContent: '(kicad_pcb)', layers: 2 });

    const appel = transport.longCallFetch.mock.calls[0];
    const corps = JSON.parse((appel?.[1] as { body: string }).body);
    expect('progress_key' in corps).toBe(false);
  });
});
