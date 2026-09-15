import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

/**
 * La 3D interactive (`Board3DView`) — ce que ces tests discriminent :
 *
 *  - l'URL demandée est celle du modèle GLB du projet, versionnée ;
 *  - tant que le serveur n'a pas répondu, un état de chargement est montré et
 *    AUCUN canvas Three.js n'est monté (un canvas monté sur une 502 rendrait
 *    un écran vide sans explication) ;
 *  - une fois le modèle disponible, le canvas est monté avec les contrôles
 *    d'orbite (c'est eux qui donnent « je clique et je tourne ») ;
 *  - une erreur du serveur est montrée avec SON message, et « Retry »
 *    re-demande ;
 *  - « Photo » bascule sur le rendu raytracé et « Interactif » revient.
 *
 * Three.js n'a pas de WebGL sous jsdom : `@react-three/fiber` et `drei` sont
 * remplacés par des témoins qui enregistrent ce qui est monté.
 */

const temoins = vi.hoisted(() => ({ orbit: vi.fn(), glb: vi.fn(), canvas: vi.fn() }));

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children, ...props }: { children?: React.ReactNode; flat?: boolean; 'data-testid'?: string }) => {
    temoins.canvas(props);
    return <div data-testid={props['data-testid'] ?? 'canvas'}>{children}</div>;
  },
  // Pas de WebGL : l'environnement local ne s'installe pas, mais le composant se monte.
  useThree: () => undefined,
}));
vi.mock('@react-three/drei', async () => {
  const { Object3D } = await import('three');
  return {
    OrbitControls: (props: Record<string, unknown>) => { temoins.orbit(props); return <div data-testid="orbit-controls" />; },
    useGLTF: (url: string) => { temoins.glb(url); return { scene: new Object3D(), parser: { json: {}, associations: new Map() } }; },
  };
});
vi.mock('@/widgets/viewer/ui/RenderView', () => ({
  RenderView: ({ family }: { family: string }) => <div data-testid="render-view">photo:{family}</div>,
}));

import { Board3DView, modelUrl, SCENE_KICAD } from '@/widgets/viewer/ui/Board3DView';

const GLB = new Uint8Array([0x67, 0x6c, 0x54, 0x46, 2, 0, 0, 0, 12, 0, 0, 0]);

function reponseGlb(): Response {
  return new Response(GLB, { status: 200, headers: { 'Content-Type': 'model/gltf-binary' } });
}
function reponseErreur(status: number, error: string): Response {
  return new Response(JSON.stringify({ success: false, error }), { status, headers: { 'Content-Type': 'application/json' } });
}

beforeEach(() => vi.clearAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe('modelUrl', () => {
  it('nomme le modèle du projet, versionné, sans paramètre superflu', () => {
    expect(modelUrl('p1')).toBe('/api/projects/p1/model');
    expect(modelUrl('p1', 3)).toBe('/api/projects/p1/model?v=3');
    expect(modelUrl('p1', 3, 2)).toBe('/api/projects/p1/model?v=3&r=2');
  });
  it('« carte nue » se dit `components=0`, et seulement dans ce cas', () => {
    expect(modelUrl('p1', 3, 0, { components: false })).toBe('/api/projects/p1/model?v=3&components=0');
    expect(modelUrl('p1', 3, 0, { components: true })).toBe('/api/projects/p1/model?v=3');
  });
});

describe('option composants', () => {
  it('le bouton bascule entre la carte avec composants et la carte nue, et le serveur dit ce qu’il a', async () => {
    const fetchMock = vi.fn(async (url: string) => new Response(GLB, {
      status: 200,
      headers: { 'Content-Type': 'model/gltf-binary', ...(url.includes('components=0') ? {} : { 'X-Model-Components': '0/9' }) },
    }));
    vi.stubGlobal('fetch', fetchMock);
    render(<Board3DView projectId="p1" version={4} />);
    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());
    // Avec composants par défaut ; le serveur n'a aucun modèle : on le dit, on ne le cache pas.
    expect(screen.getByLabelText('Toggle components').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByTestId('board-3d-composants')).toHaveTextContent('aucun modèle 3D installé sur le service (0/9)');

    fireEvent.click(screen.getByLabelText('Toggle components'));
    await waitFor(() => expect(String((fetchMock.mock.calls.at(-1) as unknown[])[0])).toBe('/api/projects/p1/model?v=4&components=0'));
    await waitFor(() => expect(screen.getByTestId('board-3d-composants')).toHaveTextContent('carte nue'));
    expect(screen.getByLabelText('Toggle components').getAttribute('aria-pressed')).toBe('false');
  });
});

describe('Board3DView', () => {
  it('demande le modèle du projet, puis monte le canvas avec les contrôles d’orbite', async () => {
    const fetchMock = vi.fn(async () => reponseGlb());
    vi.stubGlobal('fetch', fetchMock);
    render(<Board3DView projectId="p1" version={4} />);
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.queryByTestId('board-3d-canvas')).toBeNull();

    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe('/api/projects/p1/model?v=4');
    expect(screen.getByTestId('orbit-controls')).toBeInTheDocument();
    expect(temoins.glb).toHaveBeenCalledWith('/api/projects/p1/model?v=4');
    const options = temoins.orbit.mock.calls[0]?.[0] as Record<string, unknown>;
    expect(options['enableDamping']).toBe(true);
    expect(screen.queryByRole('status')).toBeNull();
  });

  it('le visualiseur de KiCad : degrade gris-bleu derriere un canvas transparent, sans tone mapping, en espace d affichage', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reponseGlb()));
    render(<Board3DView projectId="p1" />);
    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());
    const fond = screen.getByTestId('board-3d-fond').getAttribute('style') ?? '';
    expect(fond).toContain('linear-gradient');
    const props = temoins.canvas.mock.calls[0]?.[0] as { flat?: boolean; linear?: boolean; gl?: { alpha?: boolean } };
    expect(props.flat).toBe(true);
    // KiCad mélange vernis et cuivre en espace d'affichage : en linéaire, le FR4
    // olive l'emportait sous le vernis et les pistes disparaissaient (capture du 2026-09-15).
    expect(props.linear).toBe(true);
    expect(props.gl?.alpha).toBe(true);
    expect(SCENE_KICAD.environnement).toBeGreaterThan(0); // sans environnement, les métaux sortent noirs
  });

  it('montre le message du serveur sur une erreur, sans canvas, et Retry re-demande', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(reponseErreur(502, '3D export failed: Failed to load board'))
      .mockResolvedValueOnce(reponseGlb());
    vi.stubGlobal('fetch', fetchMock);
    render(<Board3DView projectId="p1" />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText('3D export failed: Failed to load board')).toBeInTheDocument();
    expect(screen.queryByTestId('board-3d-canvas')).toBeNull();

    fireEvent.click(screen.getByText('Retry'));
    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('« Photo » bascule sur le rendu raytracé 3D, « Interactif » revient', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reponseGlb()));
    render(<Board3DView projectId="p1" />);
    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());

    fireEvent.click(screen.getByLabelText('Photo render'));
    expect(screen.getByTestId('render-view')).toHaveTextContent('photo:3d');
    expect(screen.queryByTestId('board-3d-canvas')).toBeNull();

    fireEvent.click(screen.getByText('Interactif'));
    await waitFor(() => expect(screen.getByTestId('board-3d-canvas')).toBeInTheDocument());
  });
});
