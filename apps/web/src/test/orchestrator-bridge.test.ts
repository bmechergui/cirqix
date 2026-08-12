import { beforeEach, describe, expect, it, vi } from 'vitest';

const agentsMock = vi.hoisted(() => ({ runOrchestrator: vi.fn() }));
vi.mock('@cirqix/agents', () => agentsMock);
vi.mock('../app/api/agent/lib/kicad-storage', () => ({
  uploadKicadArtifact: vi.fn().mockResolvedValue({ signedUrl: undefined }),
}));
vi.mock('@cirqix/logger', () => ({
  logger: { child: () => ({ info: vi.fn(), warn: vi.fn(), error: vi.fn(), debug: vi.fn() }) },
}));

import { CreditDeductionError } from '../app/api/agent/lib/credits';
import { runRealOrchestrator } from '../app/api/agent/lib/orchestrator-bridge';

function makeController() {
  const chunks: string[] = [];
  const decoder = new TextDecoder();
  return {
    chunks,
    controller: { enqueue: (bytes: Uint8Array) => chunks.push(decoder.decode(bytes)) },
  };
}

function makeClient(rpcError: { message: string } | null = null) {
  const updates: Array<Record<string, unknown>> = [];
  const rpc = vi.fn().mockResolvedValue({ data: true, error: rpcError });
  return {
    rpc,
    updates,
    client: {
      rpc,
      from: () => ({
        update: (payload: Record<string, unknown>) => {
          updates.push(payload);
          return { eq: async () => ({ error: null }) };
        },
      }),
    },
  };
}

function finalEvents() {
  return (async function* () {
    yield { type: 'pcb_state', state: { pcb_status: 'DRC_CLEAN', iteration: 1 } };
    yield { type: 'done' };
  })();
}

beforeEach(() => {
  vi.clearAllMocks();
  agentsMock.runOrchestrator.mockImplementation(finalEvents);
});

describe('orchestrator finalization', () => {
  it('ne publie ni ne persiste DRC_CLEAN si la transaction finale échoue', async () => {
    const { client, updates } = makeClient({ message: 'insufficient_credits' });
    const { controller, chunks } = makeController();

    await expect(runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    })).rejects.toBeInstanceOf(CreditDeductionError);

    expect(updates).toHaveLength(0);
    expect(chunks.join('')).not.toContain('DRC_CLEAN');
    expect(chunks.join('')).not.toContain('"type":"done"');
  });

  it('ne persiste pas iteration_count sur les étapes intermédiaires', async () => {
    // `iteration` est figé à iterationStart + 1 pour tout le run
    // (orchestrator-bridge.ts, `mergedState.iteration ?? iterationStart + 1`).
    // Si une étape intermédiaire écrivait déjà cette valeur dans
    // projects.iteration_count, la garde `stale_iteration` de
    // finalize_pipeline_success — qui exige p_iteration_count = iteration_count
    // + 1 — refuserait la finalisation, et le pipeline échouerait à sa toute
    // dernière étape sans facturer ni promouvoir. Le compteur n'appartient
    // qu'à la RPC.
    const { client, updates } = makeClient();
    const { controller } = makeController();
    agentsMock.runOrchestrator.mockImplementation(() => (async function* () {
      yield { type: 'pcb_state', state: { pcb_status: 'ROUTING_DONE', iteration: 1 } };
      yield { type: 'pcb_state', state: { pcb_status: 'DRC_CLEAN', iteration: 1 } };
      yield { type: 'done' };
    })());

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(updates).toHaveLength(1);
    expect(updates[0]).not.toHaveProperty('iteration_count');
  });

  it('publie DRC_CLEAN et done après la transaction finale réussie', async () => {
    const { client, rpc } = makeClient();
    const { controller, chunks } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(rpc).toHaveBeenCalledWith(
      'finalize_pipeline_success',
      expect.objectContaining({ p_project_id: 'p1', p_iteration_count: 1 }),
    );
    expect(chunks.join('')).toContain('DRC_CLEAN');
    expect(chunks.join('')).toContain('"type":"done"');
  });
});

/**
 * Le chemin que le PROMPT IMPOSE — et que rien ne parcourait.
 *
 * `prompts.ts` fait enchaîner l'export après le DRC. Un pipeline qui réussit
 * complètement passe donc par DRC_CLEAN *puis* PCB_LIVRÉ. Or les tests
 * ci-dessus s'arrêtent tous à `DRC_CLEAN → done`.
 *
 * Conséquence mesurée le 2026-08-12 : `lastStatus` valait `PCB_LIVRÉ` au `done`,
 * la garde `lastStatus !== 'DRC_CLEAN'` levait, `finalizePipelineSuccess`
 * n'était JAMAIS appelé — donc AUCUN débit — alors que le board, ses Gerbers et
 * `agent_mode: 'orchestrator'` venaient d'être persistés. Le gate JLCPCB accepte
 * `PCB_LIVRÉ` : le board était commandable, fabricable, et gratuit.
 *
 * C'est le miroir des défauts corrigés cette semaine. Toutes les gardes
 * existantes vérifient qu'un statut n'est pas accordé SANS contrôle ; aucune ne
 * vérifiait qu'un contrôle réussi aboutit bien à un DÉBIT.
 *
 * Trouvé par deux audits externes indépendants (Grok, Codex), le même jour.
 */
describe('pipeline complet — DRC puis export', () => {
  function pipelineComplet() {
    return (async function* () {
      yield { type: 'pcb_state', state: { pcb_status: 'DRC_CLEAN', iteration: 1 } };
      yield {
        type: 'pcb_state',
        state: { pcb_status: 'PCB_LIVRÉ', iteration: 1, zip_b64: 'UEsDBA==', bom_csv: 'ref,lcsc' },
      };
      yield { type: 'done' };
    })();
  }

  it('facture le pipeline quand il va jusqu\'à l\'export', async () => {
    agentsMock.runOrchestrator.mockImplementation(pipelineComplet);
    const { client, rpc } = makeClient();
    const { controller } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(rpc).toHaveBeenCalledWith(
      'finalize_pipeline_success',
      expect.objectContaining({ p_project_id: 'p1', p_iteration_count: 1 }),
    );
  });

  it('n\'émet aucune erreur SSE sur un run réussi', async () => {
    // Le `throw` interne est avalé par le catch de fin (il ne contient ni
    // « credit » ni « 402 »), donc l'appel se terminait NORMALEMENT tout en
    // envoyant « Orchestrator completed without a DRC_CLEAN state » à
    // l'utilisateur — une erreur affichée sur un pipeline parfaitement réussi.
    agentsMock.runOrchestrator.mockImplementation(pipelineComplet);
    const { client } = makeClient();
    const { controller, chunks } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(chunks.join('')).not.toContain('without a DRC_CLEAN state');
    expect(chunks.join('')).toContain('"type":"done"');
  });

  it('finalise avec le statut RÉELLEMENT atteint, pas un DRC_CLEAN forcé', async () => {
    // L'export livré est un état strictement plus avancé que le DRC seul.
    // Rétrograder l'état persisté effacerait les Gerbers du statut et
    // ferait « reculer » le projet aux yeux de l'utilisateur.
    agentsMock.runOrchestrator.mockImplementation(pipelineComplet);
    const { client, rpc } = makeClient();
    const { controller } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    const args = rpc.mock.calls[0]?.[1] as { p_pcb_state: { status: string } };
    expect(args.p_pcb_state.status).toBe('PCB_LIVRÉ');
  });

  it('refuse toujours de finaliser un run qui n\'a jamais atteint le DRC', async () => {
    // La garde d'origine protégeait contre ça, et doit continuer de le faire :
    // un run interrompu à ROUTING_DONE ne se facture pas.
    agentsMock.runOrchestrator.mockImplementation(() =>
      (async function* () {
        yield { type: 'pcb_state', state: { pcb_status: 'ROUTING_DONE', iteration: 1 } };
        yield { type: 'done' };
      })(),
    );
    const { client, rpc } = makeClient();
    const { controller } = makeController();

    await runRealOrchestrator({
      controller: controller as never,
      encoder: new TextEncoder(),
      supabase: client as never,
      userId: 'u1',
      projectId: 'p1',
      prompt: 'board',
      iterationStart: 0,
    });

    expect(rpc).not.toHaveBeenCalled();
  });
});
