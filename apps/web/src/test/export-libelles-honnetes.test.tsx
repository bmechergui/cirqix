import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import type { PCBState } from '@cirqix/types';

/**
 * L'écran d'export ne dit que ce que le produit fait — relevé au parcours local
 * du 2026-09-19, sur un board livré :
 *
 *  - le fichier de placement (CPL, `pos.csv`) EST produit — il est dans le ZIP
 *    des Gerbers — mais la carte affichait « Run export to generate », comme si
 *    l'export n'avait pas tourné ;
 *  - l'export STEP n'existe pas, et affichait la même invitation ;
 *  - la BOM promettait « LCSC part numbers for JLCPCB PCBA » alors que sa
 *    colonne `lcsc` est VIDE sur tous les boards livrés (mesuré en base).
 */

vi.mock('@/shared/store/app-store', () => ({
  useAppStore: (selector: (s: unknown) => unknown) => selector({ credits: { plan: 'free' } }),
}));
vi.mock('@/widgets/viewer/ui/View3D', () => ({ View3D: () => <div data-testid="view3d" /> }));

import { ExportView } from '@/widgets/viewer/ui/ExportView';

const LIVRE = {
  status: 'PCB_LIVRÉ', projectId: 'p1', iteration: 1,
  gerberZipB64: 'UEsDBAo=', bomCsv: 'ref,value,lcsc\nR1,1k,\n',
} as unknown as PCBState;

function carte(titre: RegExp): HTMLElement {
  const libelle = screen.getByText(titre);
  const racine = libelle.closest('div.rounded-xl');
  if (!racine) throw new Error(`carte introuvable pour ${titre}`);
  return racine as HTMLElement;
}

describe('ExportView — des libellés qui disent la vérité', () => {
  it("le CPL, produit dans le ZIP des Gerbers, ne demande pas de relancer l'export", () => {
    render(<ExportView state={LIVRE} />);
    const cpl = carte(/Pick & Place/);
    expect(within(cpl).queryByText(/Run export to generate/i)).toBeNull();
    expect(within(cpl).getByText(/Gerber ZIP/i)).toBeInTheDocument();
  });

  it("le STEP, non implémenté, le dit au lieu d'inviter à relancer l'export", () => {
    render(<ExportView state={LIVRE} />);
    const step = carte(/3D STEP/);
    expect(within(step).queryByText(/Run export to generate/i)).toBeNull();
    expect(within(step).getByText(/not available yet/i)).toBeInTheDocument();
  });

  it('la BOM ne promet plus des références LCSC qu elle ne porte pas', () => {
    render(<ExportView state={LIVRE} />);
    expect(screen.queryByText(/with LCSC part numbers/i)).toBeNull();
    expect(screen.getByText(/LCSC part numbers are not assigned yet/i)).toBeInTheDocument();
  });

  it('avant la livraison, rien de tout cela ne se prétend disponible', () => {
    render(<ExportView state={{ ...LIVRE, status: 'ROUTING_DONE', gerberZipB64: undefined } as unknown as PCBState} />);
    expect(within(carte(/Pick & Place/)).queryByText(/Gerber ZIP/i)).toBeNull();
  });
});
