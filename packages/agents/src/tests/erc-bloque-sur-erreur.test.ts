import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Une ERREUR d'ERC ARRÊTE le pipeline. Un avertissement, non.
 *
 * Mesuré le 2026-09-14 sur le schéma NE555, en appelant la vraie route du
 * service : 44 violations, 15 erreurs, `erc_clean = false` — et le handler
 * rendait quand même `status: 'success'` avec la note « Pipeline arrêté avant
 * placement ». Or `run-driver.ts` ne s'interrompt QUE sur `status: 'error'` et
 * l'orchestrateur est un modèle qui lit cette note : **rien ne l'arrêtait**.
 * Un schéma fautif allait au placement, au routage, au DRC, à l'export, et
 * ressortait `PCB_LIVRÉ`. Une phrase qui annonce un arrêt qui n'a pas lieu est
 * la faute que ce dépôt traque partout.
 *
 * ⚠️ Les AVERTISSEMENTS ne bloquent pas, et c'est mesuré : sur ce même schéma,
 * 29 des 31 violations restantes sont `lib_symbol_issues` et
 * `footprint_link_issues` — le conteneur n'a pas de table de bibliothèques.
 * Bloquer dessus arrêterait toutes les cartes pour du bruit d'environnement.
 */

const services = vi.hoisted(() => ({
  runRealErc: vi.fn(),
  runErcFallback: vi.fn(),
}));

vi.mock('../engines/erc-service', () => ({
  runRealErc: services.runRealErc,
  ErcServiceUnavailableError: class extends Error {},
}));
vi.mock('../engines/erc-fallback', () => ({ runErcFallback: services.runErcFallback }));

import { handleErc } from '../tools/handlers/erc';
import { pcbStateCache } from '../tools/shared';

const PROJET = 'p-erc';
const SCH = '(kicad_sch (version 20240108))';

function violation(severity: 'error' | 'warning', type: string) {
  return { id: `${type}-${severity}`, severity, message: type, type };
}

beforeEach(() => {
  vi.clearAllMocks();
  pcbStateCache.set(PROJET, { kicad_sch_content: SCH } as never);
});

describe('kicad-cli a statué', () => {
  it('une erreur ARRÊTE le pipeline — status error, jamais ERC_CLEAN', async () => {
    services.runRealErc.mockResolvedValue({
      skipped: false, ercClean: false, fixedCount: 0,
      violations: [violation('error', 'power_pin_not_driven'), violation('warning', 'lib_symbol_issues')],
    });
    const r = await handleErc({}, PROJET);
    expect(r['status']).toBe('error');
    expect(r['pcb_status']).not.toBe('ERC_CLEAN');
    expect(String(r['error'])).toContain('1');
    expect(r['ercViolations']).toHaveLength(2);
  });

  it('des AVERTISSEMENTS seuls ne bloquent pas — le conteneur n’a pas de table de bibliothèques', async () => {
    services.runRealErc.mockResolvedValue({
      skipped: false, ercClean: false, fixedCount: 0,
      violations: [violation('warning', 'lib_symbol_issues'), violation('warning', 'footprint_link_issues')],
    });
    const r = await handleErc({}, PROJET);
    expect(r['status']).toBe('success');
    expect(r['pcb_status']).toBe('SCHEMA_DONE');
  });

  it('zéro violation promeut ERC_CLEAN', async () => {
    services.runRealErc.mockResolvedValue({ skipped: false, ercClean: true, fixedCount: 0, violations: [] });
    const r = await handleErc({}, PROJET);
    expect(r['status']).toBe('success');
    expect(r['pcb_status']).toBe('ERC_CLEAN');
  });

  it('la note ne promet plus un arrêt qui n’a pas lieu', async () => {
    services.runRealErc.mockResolvedValue({
      skipped: false, ercClean: false, fixedCount: 0,
      violations: [violation('warning', 'lib_symbol_issues')],
    });
    const r = await handleErc({}, PROJET);
    // Seul un `status: 'error'` arrête réellement : la note d'un succès ne
    // doit donc pas annoncer un arrêt.
    expect(String(r['note'])).not.toContain('arrêté');
  });
});

describe('repli TypeScript', () => {
  it('honore son verdict : une erreur arrête aussi', async () => {
    services.runRealErc.mockResolvedValue({ skipped: true, warning: 'kicad-cli absent' });
    services.runErcFallback.mockReturnValue({
      skipped: false, ercClean: false, fixedCount: 0, engine: 'typescript',
      violations: [violation('error', 'unconnected_pin')],
    });
    const r = await handleErc({}, PROJET);
    expect(r['status']).toBe('error');
  });

  it('ses avertissements seuls ne bloquent pas', async () => {
    services.runRealErc.mockResolvedValue({ skipped: true, warning: 'kicad-cli absent' });
    services.runErcFallback.mockReturnValue({
      skipped: false, ercClean: false, fixedCount: 0, engine: 'typescript',
      violations: [violation('warning', 'floating_net')],
    });
    const r = await handleErc({}, PROJET);
    expect(r['status']).toBe('success');
  });
});
