import { describe, it, expect, beforeEach, vi } from 'vitest';

/**
 * handleExport — dernier maillon : produit les Gerbers réellement envoyés en
 * fabrication, et le devis affiché à l'utilisateur.
 *
 * Deux enjeux distincts, tous deux liés à de l'argent réel :
 *   - `pcb_status: 'PCB_LIVRÉ'` fait partie du gate de POST /api/jlcpcb/order
 *     (`status !== 'DRC_CLEAN' && status !== 'PCB_LIVRÉ'` → 422). Le poser sans
 *     Gerbers autorise une commande sur un board dont rien n'a été exporté.
 *   - `quote_usd` est un PRIX affiché. ExportView distingue déjà un vrai devis
 *     d'un placeholder via `quoteIsReal = state.quoteUsd != null` — renvoyer un
 *     montant inventé défait cette logique et présente un prix fabriqué comme réel.
 */

vi.hoisted(() => {
  process.env['LOG_LEVEL'] = 'silent';
});

const exportMock = vi.hoisted(() => {
  class ExportServiceUnavailableError extends Error {}
  return { runRealExport: vi.fn(), ExportServiceUnavailableError };
});
vi.mock('../engines/export-service', () => exportMock);

import { handleExport } from '../tools/handlers/export';
import { pcbStateCache } from '../tools/shared';

const PCB = '(kicad_pcb (net 1 "GND"))';
const PROJECT = 'p1';

const SCHEMA = {
  components: [
    { ref: 'R1', value: '1k', lcsc: 'C11702' },
    { ref: 'D1', value: 'LED' },
  ],
  nets: [],
};

function exportResult(overrides: Record<string, unknown> = {}) {
  return {
    files: ['top.gtl', 'bottom.gbl', 'outline.gko'],
    zipB64: 'UEsDBBQ=',
    quoteUsd: 8.4,
    leadTimeDays: 5,
    skipped: false,
    ...overrides,
  };
}

beforeEach(() => {
  pcbStateCache.clear();
  exportMock.runRealExport.mockReset();
  exportMock.runRealExport.mockResolvedValue(exportResult());
});

function seedCache(overrides: Record<string, unknown> = {}) {
  pcbStateCache.set(PROJECT, {
    schema: SCHEMA,
    boardW: 50,
    boardH: 40,
    kicad_pcb_content: PCB,
    ...overrides,
  } as never);
}

describe('export réellement produit', () => {
  it('promeut PCB_LIVRÉ uniquement si un DRC propre a été enregistré en cache', async () => {
    seedCache({ drc_clean: true });

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('PCB_LIVRÉ');
    // L'export ne re-fabrique JAMAIS DRC_CLEAN — c'est le DRC qui l'accorde.
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(result['gerber_layers']).toBe(3);
    expect(result['files']).toEqual(['top.gtl', 'bottom.gbl', 'outline.gko']);
    expect(result['zip_b64']).toBe('UEsDBBQ=');
    expect(result['quote_usd']).toBe(8.4);
    expect(result['lead_time_days']).toBe(5);
  });

  it('génère le BOM CSV depuis le schéma en cache', async () => {
    seedCache({ drc_clean: true });

    const result = await handleExport(PROJECT);

    expect(String(result['bom_csv'])).toContain('R1,1k,C11702');
    expect(String(result['bom_csv'])).toContain('D1,LED,');
  });

  it('omet quote_usd et lead_time_days si le service ne les fournit pas', async () => {
    seedCache({ drc_clean: true });
    const bare = exportResult();
    delete (bare as { quoteUsd?: number }).quoteUsd;
    delete (bare as { leadTimeDays?: number }).leadTimeDays;
    exportMock.runRealExport.mockResolvedValue(bare);

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('success');
    expect(result).not.toHaveProperty('quote_usd');
    expect(result).not.toHaveProperty('lead_time_days');
    // Pas de $0 ni d'estimation inventée dans la note.
    expect(String(result['note'])).not.toMatch(/\$0\b/);
    expect(String(result['note'])).not.toContain('Estimation:');
  });
});

/**
 * Invariant (2026-08) : l'export ne crée jamais un statut de validation.
 * Un board DRC sale ou jamais validé peut produire des Gerbers, mais ne doit
 * ni repromouvoir DRC_CLEAN ni poser PCB_LIVRÉ — le bridge conserve lastStatus
 * (?? lastStatus) et le gate JLCPCB reste fermé.
 */
describe('export ne fabrique aucun statut de validation', () => {
  it('après un DRC non propre → succès avec fichiers, sans pcb_status', async () => {
    seedCache({ drc_clean: false });

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['zip_b64']).toBe('UEsDBBQ=');
    expect(result['gerber_layers']).toBe(3);
    expect(result).not.toHaveProperty('pcb_status');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(result['pcb_status']).not.toBe('PCB_LIVRÉ');
  });

  it('sans DRC préalable (cache sans drc_clean) → aucun statut de validation', async () => {
    seedCache(); // pas de drc_clean

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['zip_b64']).toBe('UEsDBBQ=');
    expect(result).not.toHaveProperty('pcb_status');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
    expect(result['pcb_status']).not.toBe('PCB_LIVRÉ');
  });

  it('DRC propre → PCB_LIVRÉ (sémantique documentée), jamais DRC_CLEAN', async () => {
    seedCache({ drc_clean: true });

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('success');
    expect(result['pcb_status']).toBe('PCB_LIVRÉ');
    expect(result['pcb_status']).not.toBe('DRC_CLEAN');
  });
});

describe('export sans livrable → échec', () => {
  /**
   * Un export avec files:[] ou sans zip_b64 n'a rien à livrer. Le handler
   * réussissait auparavant et l'UI pouvait traiter quoteUsd=0 comme un devis réel.
   */
  it('files vide → erreur, aucun statut de livraison', async () => {
    seedCache();
    exportMock.runRealExport.mockResolvedValue(
      exportResult({ files: [], zipB64: 'UEsDBBQ=' }),
    );

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('error');
    expect(result).not.toHaveProperty('zip_b64');
    expect(result).not.toHaveProperty('quote_usd');
    expect(result['pcb_status']).not.toBe('PCB_LIVRÉ');
  });

  it('zip_b64 absent → erreur, files seuls ne suffisent pas', async () => {
    seedCache();
    const bare = exportResult({ files: ['top.gtl'] });
    delete (bare as { zipB64?: string }).zipB64;
    exportMock.runRealExport.mockResolvedValue(bare);

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('error');
    expect(String(result['error'])).toMatch(/zip_b64/i);
    expect(result).not.toHaveProperty('zip_b64');
  });

  it('zip_b64 chaîne vide → erreur également', async () => {
    seedCache();
    exportMock.runRealExport.mockResolvedValue(exportResult({ zipB64: '' }));

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('error');
  });
});

describe('jamais de PCB_LIVRÉ ni de devis sans export réel', () => {
  /**
   * Les trois chemins ci-dessous posaient PCB_LIVRÉ sans aucun Gerber, et deux
   * d'entre eux FABRIQUAIENT `gerber_layers: 7` et `quote_usd: 12.5` — un prix
   * inventé, présenté comme réel, accompagné d'une note invitant l'utilisateur
   * à répondre « OUI JE CONFIRME » pour commander.
   */
  it.each([
    [
      'aucun PCB en cache',
      () => {
        /* cache laissé vide */
      },
      () => undefined,
    ],
    [
      'service ayant sauté l’export',
      () => seedCache(),
      () =>
        exportMock.runRealExport.mockResolvedValue(
          exportResult({ skipped: true, files: [], warning: 'kicad-cli indisponible' }),
        ),
    ],
    [
      'service injoignable',
      () => seedCache(),
      () =>
        exportMock.runRealExport.mockRejectedValue(
          new exportMock.ExportServiceUnavailableError('KICAD_SERVICE_URL not configured'),
        ),
    ],
  ])('%s → erreur, aucun statut ni devis fabriqué', async (_label, arrangeCache, arrangeService) => {
    arrangeCache();
    arrangeService();

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('PCB_LIVRÉ');
    expect(result).not.toHaveProperty('quote_usd');
    expect(result).not.toHaveProperty('gerber_layers');
    expect(result).not.toHaveProperty('zip_b64');
  });

  it('n’invite JAMAIS à commander sur un export échoué', async () => {
    seedCache();
    exportMock.runRealExport.mockRejectedValue(new Error('down'));

    const result = await handleExport(PROJECT);

    expect(String(result['note'])).not.toContain('OUI JE CONFIRME');
  });

  it('conserve le BOM CSV réel — c’est une donnée vraie, pas une fabrication', async () => {
    seedCache();
    exportMock.runRealExport.mockRejectedValue(new Error('down'));

    const result = await handleExport(PROJECT);

    expect(String(result['bom_csv'])).toContain('R1,1k,C11702');
  });

  it('erreur inattendue → erreur également', async () => {
    seedCache();
    exportMock.runRealExport.mockRejectedValue(new TypeError('bug inattendu'));

    const result = await handleExport(PROJECT);

    expect(result['status']).toBe('error');
    expect(result['pcb_status']).not.toBe('PCB_LIVRÉ');
  });

  it('mentionne KICAD_SERVICE_URL pour orienter le diagnostic', async () => {
    seedCache();
    exportMock.runRealExport.mockRejectedValue(new Error('down'));

    const result = await handleExport(PROJECT);

    expect(String(result['note'])).toContain('KICAD_SERVICE_URL');
  });
});
