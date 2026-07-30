import type { SupabaseClient } from '@supabase/supabase-js';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'credits' });

/** Fixed cost of a full PCB pipeline run (until per-step billing is wired). */
export const PIPELINE_COST = 8.5;

export class CreditDeductionError extends Error {
  constructor(cause: unknown) {
    super('Pipeline credit deduction failed', { cause });
    this.name = 'CreditDeductionError';
  }
}

export function hasEnoughPipelineCredits(balance: number): boolean {
  return Number.isFinite(balance) && balance >= PIPELINE_COST;
}

export function shouldFallbackToLocalPipeline(error: unknown): boolean {
  if (error instanceof CreditDeductionError) {
    return false;
  }
  const message = error instanceof Error ? error.message : String(error);
  return message.includes('credit') || message.includes('402');
}

/**
 * Deduct the PCB-pipeline cost atomically through the secured
 * `deduct_credits` RPC, which takes a row lock, verifies the balance and
 * records an audit row in `credit_transactions`.
 *
 * Any RPC failure is propagated. This function never falls back to a direct
 * table update: all balance changes must remain atomic and audited.
 */
export async function deductPipelineCost(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
): Promise<void> {
  const { error } = await supabase.rpc('deduct_credits', {
    p_user_id: userId,
    p_amount: PIPELINE_COST,
    p_action: 'full_pcb_pipeline',
    p_project_id: projectId,
  });

  if (error) {
    log.error({ err: error, userId }, 'deduct_credits RPC failed');
    throw new CreditDeductionError(error);
  }
}
