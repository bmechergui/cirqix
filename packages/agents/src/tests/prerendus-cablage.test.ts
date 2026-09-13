import { describe, it, expect, vi } from 'vitest';

/**
 * Le CÂBLAGE des pré-rendus : une règle correcte jamais appelée est
 * indistinguable d'une règle absente (leçon du Géomètre). Ce que ces tests
 * discriminent : sur `done`, le dernier board déposé est pré-rendu et déposé
 * sous sa clé ; sans board, rien ; et le pipeline rend `ok` SANS attendre les
 * rendus (un service lent ne retient pas la clôture du run).
 */
vi.hoisted(() => { process.env['LOG_LEVEL'] = 'silent'; });
vi.mock('../orchestrator', () => ({ runOrchestrator: vi.fn() }));
const rendu = vi.hoisted(() => ({ runRealRender: vi.fn() }));
vi.mock('../engines/render-service', () => rendu);

import { runOrchestratorPipeline } from '../pipeline/run-orchestrator';
import { PRERENDUS, cleDeRendu } from '../pipeline/render-cache';
import type { SSEEvent } from '../orchestrator';
import type { PipelineStore } from '../pipeline/store';

const BOARD = '(kicad_pcb (version 20240108) (generator pcbnew))';

function faux() {
  const rendus: string[] = [];
  const store: PipelineStore = {
    uploadArtifact: async () => ({ signedUrl: 'https://x/pcb' }),
    persistProgress: async () => undefined,
    finalizeSuccess: async () => undefined,
    uploadRender: async (cle) => { rendus.push(cle); },
  };
  const sink = { emit: async () => undefined, close: async () => undefined };
  return { store, sink: sink as never, rendus };
}
async function* source(evs: SSEEvent[]): AsyncGenerator<SSEEvent> { for (const e of evs) yield e; }

const LIVRE: SSEEvent[] = [
  { type: 'pcb_state', state: { pcb_status: 'PCB_LIVRÉ', kicad_pcb_content: BOARD } } as unknown as SSEEvent,
  { type: 'done', fullText: 'fin' } as unknown as SSEEvent,
];

describe('pré-rendus — câblage sur done', () => {
  it('rend et dépose top + iso du dernier board déposé, sans retenir le run', async () => {
    const attentes: Array<(png: Uint8Array) => void> = [];
    rendu.runRealRender.mockImplementation(() => new Promise<Uint8Array>((resolve) => { attentes.push(resolve); }));
    const tick = () => new Promise<void>((r) => setTimeout(r, 0));
    const { store, sink, rendus } = faux();
    let promesse: Promise<number> | null = null;

    const issue = await runOrchestratorPipeline({
      sink, store, projectId: 'p', prompt: 'x', iterationStart: 0,
      source: source(LIVRE), onPrerendus: (p) => { promesse = p; },
    });

    // Le run est clos AVANT que le premier rendu n'ait abouti.
    expect(issue).toEqual({ ok: true });
    expect(rendus).toEqual([]);
    expect(promesse).not.toBeNull();

    while (attentes.length < 1) await tick();
    attentes[0]!(new Uint8Array([1, 2, 3]));
    while (attentes.length < 2) await tick();
    attentes[1]!(new Uint8Array([4, 5, 6]));
    expect(await promesse!).toBe(2);
    const board = new Uint8Array(Buffer.from(BOARD, 'utf-8'));
    expect(rendus).toEqual(PRERENDUS.map((p) => cleDeRendu(board, p)));
  });

  it('sans board déposé, aucun rendu n’est demandé', async () => {
    rendu.runRealRender.mockReset();
    const { store, sink } = faux();
    let promesse: Promise<number> | null = null;
    await runOrchestratorPipeline({
      sink, store, projectId: 'p', prompt: 'x', iterationStart: 0,
      source: source([{ type: 'pcb_state', state: { pcb_status: 'PCB_LIVRÉ' } } as unknown as SSEEvent, { type: 'done', fullText: 'fin' } as unknown as SSEEvent]),
      onPrerendus: (p) => { promesse = p; },
    });
    expect(promesse).toBeNull();
    expect(rendu.runRealRender).not.toHaveBeenCalled();
  });
});
