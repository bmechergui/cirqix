import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * runRealExport — mapping honnête de la réponse service.
 *
 * quote_usd / lead_time_days absents retombaient sur 0. L'UI traite
 * `quoteUsd != null` comme devis réel → $0 affiché comme estimation JLCPCB.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

vi.mock('../engines/kicad-service-auth', () => ({
  buildKicadServiceHeaders: () => ({
    'Content-Type': 'application/json',
    Authorization: 'Bearer test',
  }),
}));

import { runRealExport } from '../engines/export-service';

const fetchMock = vi.fn();

beforeEach(() => {
  process.env['KICAD_SERVICE_URL'] = 'http://kicad.test';
  fetchMock.mockReset();
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  delete process.env['KICAD_SERVICE_URL'];
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('quote / lead_time absents — jamais de défaut à 0', () => {
  it('omet quoteUsd et leadTimeDays si le service ne les renvoie pas', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        files: ['top.gtl'],
        zip_b64: 'UEsDBBQ=',
        skipped: false,
      }),
    );

    const result = await runRealExport({
      kicadPcbContent: '(kicad_pcb)',
      projectId: 'p1',
    });

    expect(result).not.toHaveProperty('quoteUsd');
    expect(result).not.toHaveProperty('leadTimeDays');
    expect(result.quoteUsd).toBeUndefined();
    expect(result.leadTimeDays).toBeUndefined();
  });

  it('propage les valeurs numériques réelles du service', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        files: ['top.gtl'],
        zip_b64: 'UEsDBBQ=',
        quote_usd: 8.4,
        lead_time_days: 5,
        skipped: false,
      }),
    );

    const result = await runRealExport({
      kicadPcbContent: '(kicad_pcb)',
      projectId: 'p1',
    });

    expect(result.quoteUsd).toBe(8.4);
    expect(result.leadTimeDays).toBe(5);
  });
});
