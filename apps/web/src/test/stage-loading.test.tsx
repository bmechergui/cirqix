import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import type { Project, PCBState } from '@cirqix/types';

/**
 * Au rechargement d'un projet LIVRÉ, l'état PCB n'est pas encore chargé : on
 * affichait l'accueil « Awaiting Prompt » pendant ce temps, comme si le projet
 * était vide. Ce que ces tests discriminent : « pas encore demandé » montre un
 * chargement, « demandé, rien » montre l'accueil, « demandé, un état » montre
 * la vue de l'étape.
 */

vi.mock('@/widgets/viewer/ui/PcbView', () => ({ PcbView: () => <div data-testid="pcb-view" /> }));
vi.mock('@/widgets/viewer/ui/ExportView', () => ({ ExportView: () => <div data-testid="export-view" /> }));
vi.mock('@/widgets/viewer/ui/SimulationView', () => ({ SimulationView: () => <div data-testid="simulation-view" /> }));
vi.mock('@/widgets/viewer/ui/DrcView', () => ({ DrcView: () => <div data-testid="drc-view" /> }));
vi.mock('@/widgets/viewer/ui/ErcView', () => ({ ErcView: () => <div data-testid="erc-view" /> }));
vi.mock('@/widgets/viewer/ui/SchemaView', () => ({ SchemaView: () => <div data-testid="schema-view" /> }));

import { Stage } from '@/widgets/viewer/ui/Stage';
import { useAppStore } from '@/shared/store/app-store';

const PROJET = { id: 'p1', name: 'Thermo', status: 'PCB_LIVRÉ', updated_at: '2026-09-13', iteration_count: 3 } as unknown as Project;
const ETAT = { status: 'PCB_LIVRÉ', projectId: 'p1', iteration: 3, kicad_pcb_url: 'https://x/pcb' } as unknown as PCBState;

function reponse(state: PCBState | null): Response {
  return new Response(JSON.stringify({ success: true, data: { pcb_state: state } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
}

beforeEach(() => {
  useAppStore.setState({ pcbStateByProject: {}, selectedStage: {} });
});
afterEach(() => vi.unstubAllGlobals());

describe('Stage — l’état PCB au chargement', () => {
  it('montre un chargement, jamais « Awaiting Prompt », tant que l’état n’est pas revenu', () => {
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(() => { /* jamais */ })));
    render(<Stage project={PROJET} />);
    expect(screen.getByTestId('stage-loading')).toBeInTheDocument();
    expect(screen.queryByText('Awaiting Prompt')).toBeNull();
  });

  it('un projet livré affiche la vue de son étape dès que l’état est revenu', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reponse(ETAT)));
    render(<Stage project={PROJET} />);
    await waitFor(() => expect(screen.getByTestId('export-view')).toBeInTheDocument());
    expect(screen.queryByText('Awaiting Prompt')).toBeNull();
  });

  it('un projet sans état (jamais généré) affiche l’accueil', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => reponse(null)));
    render(<Stage project={{ ...PROJET, status: 'INITIAL' } as Project} />);
    await waitFor(() => expect(screen.getByText('Awaiting Prompt')).toBeInTheDocument());
    expect(screen.queryByTestId('stage-loading')).toBeNull();
  });
});
