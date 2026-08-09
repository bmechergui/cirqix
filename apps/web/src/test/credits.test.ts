import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@cirqix/logger', () => ({
  logger: {
    child: () => ({
      info: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    }),
  },
}));

import {
  CreditDeductionError,
  finalizePipelineSuccess,
  hasEnoughPipelineCredits,
  PIPELINE_COST,
  shouldFallbackToLocalPipeline,
} from '../app/api/agent/lib/credits';

function makeSupabase(rpcError: { message: string } | null = null) {
  const update = vi.fn();
  const from = vi.fn(() => ({ update }));
  const rpc = vi.fn().mockResolvedValue({ data: true, error: rpcError });

  return { client: { rpc, from }, rpc, from, update };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('finalizePipelineSuccess', () => {
  it('facture et promeut le projet avec une seule RPC transactionnelle', async () => {
    const { client, rpc, from } = makeSupabase();
    const state = { projectId: 'project-1', iteration: 3, status: 'DRC_CLEAN' };

    await finalizePipelineSuccess(client as never, 'user-1', 'project-1', state as never, 'orchestrator');

    expect(rpc).toHaveBeenCalledWith('finalize_pipeline_success', {
      p_user_id: 'user-1',
      p_project_id: 'project-1',
      p_iteration_count: 3,
      p_pcb_state: state,
      p_agent_mode: 'orchestrator',
    });
    expect(from).not.toHaveBeenCalled();
  });

  it('refuse de finaliser un état autre que DRC_CLEAN', async () => {
    const { client, rpc } = makeSupabase();

    await expect(finalizePipelineSuccess(
      client as never,
      'user-1',
      'project-1',
      { projectId: 'project-1', iteration: 3, status: 'ROUTING_DONE' } as never,
      'orchestrator',
    )).rejects.toBeInstanceOf(CreditDeductionError);
    expect(rpc).not.toHaveBeenCalled();
  });

  it('refuse un retry obsolète lorsque la RPC signale une itération déjà finalisée', async () => {
    const rpc = vi.fn().mockResolvedValue({ data: false, error: null });

    await expect(finalizePipelineSuccess(
      { rpc } as never,
      'user-1',
      'project-1',
      { projectId: 'project-1', iteration: 3, status: 'DRC_CLEAN' } as never,
      'orchestrator',
    )).rejects.toBeInstanceOf(CreditDeductionError);
  });
});

describe('pipeline credit gate', () => {
  it('refuse tout solde inférieur au coût complet', () => {
    expect(hasEnoughPipelineCredits(PIPELINE_COST - 0.01)).toBe(false);
  });

  it('accepte exactement le coût complet', () => {
    expect(hasEnoughPipelineCredits(PIPELINE_COST)).toBe(true);
  });
});

describe('orchestrator fallback', () => {
  it('n’utilise jamais le fallback après un échec de débit utilisateur', () => {
    expect(shouldFallbackToLocalPipeline(new CreditDeductionError('rpc failed'))).toBe(false);
  });

  it('conserve le fallback sur le statut 402 du SDK Anthropic', () => {
    expect(shouldFallbackToLocalPipeline(Object.assign(new Error('quota'), { status: 402 })))
      .toBe(true);
  });

  it('conserve le fallback sur le message exact de quota Anthropic', () => {
    expect(shouldFallbackToLocalPipeline(
      new Error('Your credit balance is too low to access the Anthropic API'),
    )).toBe(true);
  });

  // Le repli local persiste `agent_mode: 'orchestrator'` pour un pipeline
  // tronqué (5 étapes sur 8) : l'armer à tort rend commandable un board sans
  // footprints résolus ni export. Ces trois erreurs le déclenchaient avant le
  // correctif, par simple présence de « credit » ou « 402 » dans le message.
  it('ne bascule pas sur une erreur Supabase mentionnant la table credits', () => {
    expect(shouldFallbackToLocalPipeline(
      new Error('relation "credits" does not exist'),
    )).toBe(false);
  });

  it('ne bascule pas sur une erreur applicative citant les crédits', () => {
    expect(shouldFallbackToLocalPipeline(new Error('failed to read credit row'))).toBe(false);
  });

  it('ne bascule pas sur un 402 qui n’est pas un statut HTTP', () => {
    expect(shouldFallbackToLocalPipeline(new Error('board width 402 mm invalid'))).toBe(false);
  });
});

describe('facturation du pipeline — un seul chemin', () => {
  // `deductPipelineCost` débitait PIPELINE_COST sans aucun appelant de
  // production, alors que `finalize_pipeline_success` débite déjà ce montant en
  // interne : la câbler aurait facturé 17 crédits pour un pipeline. Ce test
  // empêche sa réintroduction silencieuse.
  it('n’expose plus de débit du pipeline hors finalisation', async () => {
    const mod = await import('../app/api/agent/lib/credits');
    expect(mod).not.toHaveProperty('deductPipelineCost');
  });

  it('conserve le coût de référence du pipeline', () => {
    expect(PIPELINE_COST).toBe(8.5);
  });
});
