/**
 * Le palier de départ d'un reroutage voyage jusqu'au service (2026-10-02).
 *
 * Banc dense du 2026-10-01 : carte-09 atteint 97 % à 6 couches, son placement
 * est gardé, et chaque reroutage repartait de 2 couches (82 min au total).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { palierDepartDe } from '../tools/handlers/routing';

const transport = vi.hoisted(() => ({ longCallFetch: vi.fn() }));
vi.mock('../engines/long-call-transport', () => transport);

beforeEach(() => {
  process.env['KICAD_SERVICE_URL'] = 'http://kicad.test:8766';
  process.env['KICAD_SERVICE_TOKEN'] = 'x'.repeat(40);
});

afterEach(() => {
  transport.longCallFetch.mockReset();
  vi.resetModules();
  delete process.env['KICAD_SERVICE_URL'];
  delete process.env['KICAD_SERVICE_TOKEN'];
});

function reponse(): Response {
  return new Response(JSON.stringify({ routed_percent: 100, layers: 6 }), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

describe('palier de départ', () => {
  it('runRealRouting le place dans le corps de la requête', async () => {
    transport.longCallFetch.mockResolvedValue(reponse());
    const { runRealRouting } = await import('../engines/routing-service.js');
    await runRealRouting({ kicadPcbContent: '(kicad_pcb)', layers: 8, palierDepart: 6 });
    const corps = JSON.parse((transport.longCallFetch.mock.calls[0]?.[1] as { body: string }).body);
    expect(corps.palier_depart).toBe(6);
  });

  it('absent, rien n’est envoyé : le routage part de 2 comme avant', async () => {
    transport.longCallFetch.mockResolvedValue(reponse());
    const { runRealRouting } = await import('../engines/routing-service.js');
    await runRealRouting({ kicadPcbContent: '(kicad_pcb)', layers: 8 });
    const corps = JSON.parse((transport.longCallFetch.mock.calls[0]?.[1] as { body: string }).body);
    expect(corps).not.toHaveProperty('palier_depart');
  });

  it('le handler n’accepte qu’un nombre pair ≥ 2', () => {
    expect(palierDepartDe({ palier_depart: 6 })).toBe(6);
    expect(palierDepartDe({ palier_depart: 5 })).toBeUndefined();
    expect(palierDepartDe({ palier_depart: '6' })).toBeUndefined();
    expect(palierDepartDe(undefined)).toBeUndefined();
  });
});
