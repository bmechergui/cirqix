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
  deductPipelineCost,
  hasEnoughPipelineCredits,
  PIPELINE_COST,
  shouldFallbackToLocalPipeline,
} from '../app/api/agent/lib/credits';

function makeSupabase(rpcError: { message: string } | null = null) {
  const update = vi.fn();
  const from = vi.fn(() => ({ update }));
  const rpc = vi.fn().mockResolvedValue({ error: rpcError });

  return { client: { rpc, from }, rpc, from, update };
}

beforeEach(() => {
  vi.clearAllMocks();
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

  it('conserve le fallback pour une indisponibilité de crédits Anthropic', () => {
    expect(shouldFallbackToLocalPipeline(new Error('Anthropic credit 402'))).toBe(true);
  });
});

describe('deductPipelineCost', () => {
  it('débite uniquement via la RPC atomique', async () => {
    const { client, rpc, from } = makeSupabase();

    await deductPipelineCost(client as never, 'user-1', 'project-1');

    expect(rpc).toHaveBeenCalledWith('deduct_credits', {
      p_user_id: 'user-1',
      p_amount: PIPELINE_COST,
      p_action: 'full_pcb_pipeline',
      p_project_id: 'project-1',
    });
    expect(from).not.toHaveBeenCalled();
  });

  it('propage insufficient_credits sans mutation directe de la table', async () => {
    const { client, from } = makeSupabase({ message: 'insufficient_credits' });

    await expect(
      deductPipelineCost(client as never, 'user-1', 'project-1'),
    ).rejects.toBeInstanceOf(CreditDeductionError);
    expect(from).not.toHaveBeenCalled();
  });

  it('propage toute erreur RPC', async () => {
    const { client, from } = makeSupabase({ message: 'database unavailable' });

    await expect(
      deductPipelineCost(client as never, 'user-1', 'project-1'),
    ).rejects.toBeInstanceOf(CreditDeductionError);
    expect(from).not.toHaveBeenCalled();
  });
});
