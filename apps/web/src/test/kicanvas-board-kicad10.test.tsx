import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, waitFor } from '@testing-library/react';

/**
 * Un board écrit par pcbnew 10 n'a AUCUNE table de nets : chaque piste porte
 * `(net "GND")` — le nom — là où KiCad ≤ 9 déclarait `(net 3 "GND")` en tête et
 * posait `(net 3)` sur les objets. KiCanvas ne connaît que la seconde forme :
 * un clic sur une piste plantait la page entière sur
 * `getNetNumber: Cannot read properties of undefined (reading 'number')`
 * (rapporté par l'utilisateur le 2026-09-14), et le panneau des nets était vide.
 *
 * Ce que ces tests discriminent : la table de nets est reconstruite et les
 * objets renumérotés (idempotent, un board ≤ 9 est rendu tel quel) ; et le
 * viewer confie à KiCanvas cette version normalisée (une URL blob), jamais le
 * fichier brut.
 */

vi.mock('@/widgets/viewer/lib/kicanvas-loader', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/widgets/viewer/lib/kicanvas-loader')>();
  return { ...mod, loadKiCanvas: () => Promise.resolve() };
});

import { normaliserBoardPourKiCanvas } from '@/widgets/viewer/lib/kicanvas-loader';
import { KiCanvasViewer } from '@/widgets/viewer/ui/KiCanvasViewer';

const BOARD_10 = `(kicad_pcb
\t(version 20250114)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general (thickness 1.6))
\t(setup (pad_to_mask_clearance 0))
\t(footprint "R_0603"
\t\t(layer "F.Cu")
\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "GND"))
\t\t(pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net "+3V3"))
\t)
\t(segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net "GND"))
\t(via (at 1 0) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net "+3V3"))
\t(zone (net "GND") (net_name "GND") (layer "B.Cu"))
)`;

const BOARD_9 = `(kicad_pcb
\t(version 20240108)
\t(generator "pcbnew")
\t(net 0 "")
\t(net 1 "GND")
\t(segment (start 0 0) (end 1 0) (width 0.2) (layer "F.Cu") (net 1))
)`;

describe('normaliserBoardPourKiCanvas', () => {
  it('reconstruit la table des nets et renumérote les objets d’un board KiCad 10', () => {
    const out = normaliserBoardPourKiCanvas(BOARD_10);
    expect(out).toContain('(net 0 "")');
    expect(out).toContain('(net 1 "+3V3")');
    expect(out).toContain('(net 2 "GND")');
    // La table précède le premier objet, comme dans un board KiCad ≤ 9.
    expect(out.indexOf('(net 2 "GND")')).toBeLessThan(out.indexOf('(footprint'));
    // Plus aucun net nommé sur les objets ; `net_name` des zones est conservé.
    expect(out).not.toMatch(/\(net "[^"]*"\)/);
    expect(out).toContain('(layers "F.Cu") (net 2))');
    expect(out).toContain('(net_name "GND")');
    expect(out).toContain('(zone (net 2) (net_name "GND")');
    expect((out.match(/\(net 1\)/g) ?? []).length).toBe(2);
  });

  it('rend tel quel un board qui a déjà sa table de nets', () => {
    expect(normaliserBoardPourKiCanvas(BOARD_9)).toBe(BOARD_9);
  });

  it('est idempotente', () => {
    const une = normaliserBoardPourKiCanvas(BOARD_10);
    expect(normaliserBoardPourKiCanvas(une)).toBe(une);
  });
});

describe('KiCanvasViewer', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.unstubAllGlobals());

  it('confie à KiCanvas le board normalisé EN LIGNE, sous un nom en .kicad_pcb — jamais une URL blob', async () => {
    // ⚠️ KiCanvas choisit son chargeur sur la fin de l'URL (`endsWith(".kicad_pcb")`) :
    // une URL blob donnait « No vaild root schematic was found » (2026-09-14).
    const fetchMock = vi.fn(async () => new Response(BOARD_10, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(<KiCanvasViewer src="https://stockage/x/pcb.kicad_pcb?token=1" />);
    const source = await waitFor(() => {
      const s = container.querySelector('kicanvas-embed > kicanvas-source');
      if (!s) throw new Error('source en ligne pas encore montée');
      return s;
    });
    expect(container.querySelector('kicanvas-embed')?.hasAttribute('src')).toBe(false);
    expect(source.getAttribute('name')).toMatch(/\.kicad_pcb$/);
    expect(source.textContent).toContain('(net 2 "GND")');
    expect(source.textContent).not.toMatch(/\(net "[^"]*"\)/);
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe('https://stockage/x/pcb.kicad_pcb?token=1');
  });

  it('un schéma est passé tel quel', async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    const { container } = render(<KiCanvasViewer src="https://stockage/x/schema.kicad_sch" />);
    await waitFor(() => expect(container.querySelector('kicanvas-embed')?.getAttribute('src')).toBe('https://stockage/x/schema.kicad_sch'));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('si le board ne peut pas être lu, KiCanvas reçoit l’URL d’origine', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('', { status: 500 })));
    const { container } = render(<KiCanvasViewer src="https://stockage/x/pcb.kicad_pcb" />);
    await waitFor(() => expect(container.querySelector('kicanvas-embed')?.getAttribute('src')).toBe('https://stockage/x/pcb.kicad_pcb'));
  });
});
