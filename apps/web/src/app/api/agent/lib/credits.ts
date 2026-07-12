import type { SupabaseClient } from '@supabase/supabase-js';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'credits' });

/** Fixed cost of a full PCB pipeline run (until per-step billing is wired). */
export const PIPELINE_COST = 8.5;

/**
 * Deduct the PCB-pipeline cost atomically through the secured
 * `deduct_credits` RPC, which takes a row lock, verifies the balance and
 * records an audit row in `credit_transactions`.
 *
 * Replaces the previous non-atomic direct UPDATE that bypassed the RPC
 * (race condition + missing audit trail).
 *
 * Edge case: the route only gates entry at `balance >= 0.5`, so a user
 * may legitimately reach the success path with fewer than `PIPELINE_COST`
 * credits. When the RPC raises `insufficient_credits`, the balance is
 * clamped to 0 (preserving prior behaviour) instead of failing the
 * already-succeeded response.
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

  if (!error) {
    return;
  }

  if (error.message.includes('insufficient_credits')) {
    log.warn({ userId }, 'insufficient_credits — clamping balance to 0');
    await supabase
      .from('credits')
      .update({ balance: 0, updated_at: new Date().toISOString() })
      .eq('user_id', userId);
    return;
  }

  log.error({ err: error, userId }, 'deduct_credits RPC failed');
}
