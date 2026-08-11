import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { PCBState } from '@cirqix/types';

/**
 * Vue 3D réservée aux plans payants.
 *
 * ⚠️ Différenciateur PRODUIT, pas frontière de sécurité — et ces tests ne
 * prétendent pas le contraire. `View3D` ne consomme aucun artefact serveur : il
 * dessine à partir du `PCBState` que le client possède déjà. Ce qui est testé
 * ici, c'est que l'onglet n'est pas offert et que la vue ne s'affiche pas —
 * pas qu'un utilisateur déterminé ne puisse pas reconstituer le rendu.
 *
 * Les deux autres droits du plan sont, eux, appliqués côté serveur
 * (`handleRouting`, `handleSimulation`) et testés comme tels.
 */

const storeMock = vi.hoisted(() => ({ plan: 'free' as string | undefined }));
vi.mock('@/shared/store/app-store', () => ({
  useAppStore: (selector: (s: unknown) => unknown) =>
    selector({ credits: storeMock.plan ? { plan: storeMock.plan } : null }),
}));

// `View3D` est chargé dynamiquement et tire Three.js : on le remplace par un
// marqueur, le sujet du test étant l'accès, pas le rendu.
vi.mock('@/widgets/viewer/ui/View3D', () => ({
  View3D: () => <div data-testid="view3d" />,
}));

import { ExportView } from '@/widgets/viewer/ui/ExportView';

const STATE = { status: 'DRC_CLEAN', projectId: 'p1', iteration: 1 } as unknown as PCBState;

beforeEach(() => {
  vi.clearAllMocks();
  storeMock.plan = 'free';
});

describe('ExportView — accès à la vue 3D', () => {
  it("n'offre pas l'onglet 3D à un compte gratuit", () => {
    render(<ExportView state={STATE} />);

    const tab = screen.getByRole('button', { name: /3D/i });
    expect(tab).toBeDisabled();
  });

  it('offre l\'onglet à un compte Pro', () => {
    storeMock.plan = 'pro';

    render(<ExportView state={STATE} />);

    expect(screen.getByRole('button', { name: /3D/i })).not.toBeDisabled();
  });

  it('refuse aussi quand le plan est inconnu du store', () => {
    // Le store n'a pas encore chargé les crédits : le défaut sûr est de ne pas
    // offrir la fonctionnalité, comme partout ailleurs.
    storeMock.plan = undefined;

    render(<ExportView state={STATE} />);

    expect(screen.getByRole('button', { name: /3D/i })).toBeDisabled();
  });

  it('dit ce qui débloque la vue', () => {
    render(<ExportView state={STATE} />);

    expect(screen.getByRole('button', { name: /3D/i })).toHaveAttribute(
      'title',
      expect.stringMatching(/pro/i),
    );
  });
});
