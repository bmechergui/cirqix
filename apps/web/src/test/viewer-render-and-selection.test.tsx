import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';

/**
 * Le viewer « comme KiCad » — ce que ces tests discriminent :
 *
 *  - ViewModeSwitch : les quatre modes existent, PNG et 3D sont verrouillés
 *    sans board, et un clic rend bien le mode cliqué ;
 *  - RenderView : la vue cliquée part dans l'URL (`view=front`, `yaw=30`,
 *    `quality=high`), l'image reçue est affichée, une erreur du serveur est
 *    montrée avec SON message, et « Retry » re-demande ;
 *  - KiCanvasViewer : l'élément est monté en `controls="full"` (couches, nets,
 *    propriétés — le panneau de KiCad) sans overlay de focus, et l'événement
 *    `kicanvas:select` émis par KiCanvas nomme l'objet cliqué dans le HUD.
 *    Un écouteur jamais branché passerait un test qui ne fait qu'afficher.
 */

vi.mock('@/widgets/viewer/lib/kicanvas-loader', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/widgets/viewer/lib/kicanvas-loader')>();
  return { ...mod, loadKiCanvas: () => Promise.resolve() };
});

import { ViewModeSwitch } from '@/widgets/viewer/ui/ViewModeSwitch';
import { RenderView, renderUrl } from '@/widgets/viewer/ui/RenderView';
import { KiCanvasViewer, describeSelection } from '@/widgets/viewer/ui/KiCanvasViewer';

const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]);

function reponsePng(durationMs = 1234): Response {
  return new Response(PNG, { status: 200, headers: { 'Content-Type': 'image/png', 'X-Render-Duration-Ms': String(durationMs) } });
}

function urlsDemandees(fetchMock: ReturnType<typeof vi.fn>): string[] {
  return fetchMock.mock.calls.map((c) => String((c as unknown[])[0]));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal('URL', Object.assign(URL, {
    createObjectURL: vi.fn(() => 'blob:mock'),
    revokeObjectURL: vi.fn(),
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe('ViewModeSwitch', () => {
  it('offre Native, Cirqix, PNG et 3D, et rend le mode cliqué', () => {
    const onChange = vi.fn();
    render(<ViewModeSwitch mode="native" onChange={onChange} />);
    for (const label of ['Native', 'Cirqix', 'PNG', '3D']) expect(screen.getByText(label)).toBeInTheDocument();
    fireEvent.click(screen.getByText('3D'));
    fireEvent.click(screen.getByText('PNG'));
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(['3d', 'png']);
  });

  it('sans `renders`, ni PNG ni 3D — l’étape Schéma n’a pas de board à rendre', () => {
    render(<ViewModeSwitch mode="native" onChange={vi.fn()} renders={false} />);
    expect(screen.getByText('Native')).toBeInTheDocument();
    expect(screen.queryByText('PNG')).toBeNull();
    expect(screen.queryByText('3D')).toBeNull();
  });

  it('verrouille Native, PNG et 3D sans board — seule la vue Cirqix reste', () => {
    const onChange = vi.fn();
    render(<ViewModeSwitch mode="spec" onChange={onChange} nativeDisabled />);
    for (const label of ['Native', 'PNG', '3D']) {
      const bouton = screen.getByText(label).closest('button') as HTMLButtonElement;
      expect(bouton).toBeDisabled();
      fireEvent.click(bouton);
    }
    expect(onChange).not.toHaveBeenCalled();
  });
});

describe('RenderView', () => {
  it('demande la première vue de la famille, puis la vue cliquée, la rotation et la qualité', async () => {
    const fetchMock = vi.fn(async () => reponsePng());
    vi.stubGlobal('fetch', fetchMock);
    render(<RenderView projectId="p1" family="3d" version={7} />);

    await waitFor(() => expect(screen.getByTestId('render-image')).toBeInTheDocument());
    expect(urlsDemandees(fetchMock)[0]).toContain('/api/projects/p1/render?view=iso&quality=basic&v=7');
    expect(screen.getByText('1.2 s')).toBeInTheDocument();

    fireEvent.click(screen.getByText('Front'));
    await waitFor(() => expect(urlsDemandees(fetchMock).at(-1)).toContain('view=front'));

    fireEvent.click(screen.getByLabelText('Rotate right'));
    await waitFor(() => expect(urlsDemandees(fetchMock).at(-1)).toContain('yaw=30'));

    fireEvent.click(screen.getByText('HD'));
    await waitFor(() => expect(urlsDemandees(fetchMock).at(-1)).toContain('quality=high'));
  });

  it('en famille PNG, seules Top et Bottom sont offertes, sans rotation', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reponsePng()));
    render(<RenderView projectId="p1" family="png" />);
    expect(screen.getByText('Top')).toBeInTheDocument();
    expect(screen.getByText('Bottom')).toBeInTheDocument();
    expect(screen.queryByText('Iso')).toBeNull();
    expect(screen.queryByLabelText('Rotate right')).toBeNull();
    await waitFor(() => expect(screen.getByTestId('render-image')).toBeInTheDocument());
  });

  it('montre le message du serveur en cas d’échec, et « Retry » re-demande', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ success: false, error: 'Render failed: kicad-cli pcb render failed (rc=1): Failed to load board' }), {
        status: 502, headers: { 'Content-Type': 'application/json' },
      }));
    vi.stubGlobal('fetch', fetchMock);
    render(<RenderView projectId="p1" family="png" />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent('Failed to load board');
    expect(screen.queryByTestId('render-image')).toBeNull();

    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(urlsDemandees(fetchMock)[1]).toContain('r=1');
  });

  it('renderUrl encode l’identifiant et ne met que ce qui diffère des défauts', () => {
    expect(renderUrl('a/b', { view: 'top', quality: 'basic', yaw: 0 })).toBe('/api/projects/a%2Fb/render?view=top&quality=basic');
    expect(renderUrl('p', { view: 'iso', quality: 'high', yaw: -30 }, { version: 3 })).toBe('/api/projects/p/render?view=iso&quality=high&yaw=-30&v=3');
  });
});

describe('KiCanvasViewer — sélection comme KiCad', () => {
  it('monte kicanvas-embed en controls="full" sans overlay, cadre la carte et nomme l’objet que le VIEWER sélectionne', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    // Le viewer lit le board pour le normaliser (table des nets KiCad 10) avant de le confier à KiCanvas.
    vi.stubGlobal('fetch', vi.fn(async () => new Response('(kicad_pcb (version 20240108)\n\t(net 0 "")\n)', { status: 200 })));
    try {
      const { container } = render(<KiCanvasViewer src="https://x/pcb.kicad_pcb" />);
      const embed = await waitFor(() => {
        const el = container.querySelector('kicanvas-embed');
        if (!el) throw new Error('pas encore monté');
        return el;
      });
      expect(embed.getAttribute('controls')).toBe('full');
      expect(embed.getAttribute('controlslist')).toContain('nooverlay');
      expect(embed.getAttribute('theme')).toBe('kicad'); // les couleurs de KiCad, pas witchhazel
      expect(screen.queryByTestId('kicanvas-selection')).toBeNull();

      // Le viewer de KiCanvas vit dans le shadow DOM (kicanvas-embed → kc-board-viewer.viewer)
      // et c'est un EventTarget : c'est LUI qui émet `kicanvas:select`, pas l'élément.
      // Un écouteur posé sur l'élément passait ce test et ne recevait rien en réel.
      const viewer = Object.assign(new EventTarget(), {
        loaded: Promise.resolve(true), zoom_to_board: vi.fn(), draw: vi.fn(),
      });
      const shadow = embed.attachShadow({ mode: 'open' });
      const boardViewer = document.createElement('kc-board-viewer') as HTMLElement & { viewer: unknown };
      boardViewer.viewer = viewer;
      shadow.appendChild(boardViewer);

      await act(async () => { await vi.advanceTimersByTimeAsync(300); });
      expect(viewer.zoom_to_board).toHaveBeenCalled();
      expect(viewer.draw).toHaveBeenCalled();

      act(() => {
        viewer.dispatchEvent(new CustomEvent('kicanvas:select', { detail: { item: { reference: 'U1', value: 'NE555' }, previous: null } }));
      });
      const badge = await screen.findByTestId('kicanvas-selection');
      expect(badge).toHaveTextContent('Footprint');
      expect(badge).toHaveTextContent('U1');
      expect(badge).toHaveTextContent('NE555');

      act(() => {
        viewer.dispatchEvent(new CustomEvent('kicanvas:select', { detail: { item: null, previous: null } }));
      });
      await waitFor(() => expect(screen.queryByTestId('kicanvas-selection')).toBeNull());
    } finally {
      vi.useRealTimers();
    }
  });

  it('describeSelection nomme une empreinte, une piste par son net, et rien pour le vide', () => {
    expect(describeSelection({ reference: 'C3', value: '100nF' })).toEqual({ kind: 'Footprint', label: 'C3', detail: '100nF' });
    class LineSegment { net = 4; layer = 'F.Cu'; }
    expect(describeSelection(new LineSegment())).toEqual({ kind: 'LineSegment', label: 'net 4', detail: 'F.Cu' });
    expect(describeSelection(null)).toBeNull();
    expect(describeSelection(undefined)).toBeNull();
  });
});

describe('RenderView — bascule rapide', () => {
  it('révoque ou ne crée jamais une URL blob pour un fetch dépassé par la bascule suivante', async () => {
    let resoudrePremier: (r: Response) => void = () => undefined;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((resolve) => { resoudrePremier = resolve; }))
      .mockImplementation(async () => reponsePng());
    vi.stubGlobal('fetch', fetchMock);
    const create = URL.createObjectURL as unknown as ReturnType<typeof vi.fn>;
    const revoke = URL.revokeObjectURL as unknown as ReturnType<typeof vi.fn>;

    render(<RenderView projectId="p1" family="png" />);
    fireEvent.click(screen.getByText('Bottom'));            // le premier fetch est dépassé
    await waitFor(() => expect(screen.getByTestId('render-image')).toBeInTheDocument());
    const creesAvant = create.mock.calls.length;

    await act(async () => { resoudrePremier(reponsePng()); await Promise.resolve(); await Promise.resolve(); });

    // Soit le premier n'a rien créé, soit ce qu'il a créé est révoqué : jamais une URL orpheline.
    const creesApres = create.mock.calls.length;
    expect(creesApres - creesAvant).toBeLessThanOrEqual(revoke.mock.calls.length);
    expect(creesApres - creesAvant).toBe(0);
  });
});
