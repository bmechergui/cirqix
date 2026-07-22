import type { SupabaseClient } from '@supabase/supabase-js';

/** Fixed cost of a full PCB pipeline run (until per-step billing is wired). */
export const PIPELINE_COST = 8.5;

/**
 * Reserve the PCB-pipeline cost atomically through the secured RPC. A
 * reservation does not debit the user: it only prevents concurrent pipelines
 * from spending the same balance. Stale reservations expire automatically.
 *
 * The route reserves this full amount before pipeline execution. Any RPC
 * failure is propagated; direct balance writes are never used as a fallback.
 */
export async function reservePipelineCredits(
  supabase: SupabaseClient,
  reservationId: string,
  userId: string,
  projectId: string,
): Promise<void> {
  const { error } = await supabase.rpc('reserve_pipeline_credits', {
    p_reservation_id: reservationId,
    p_user_id: userId,
    p_project_id: projectId,
    p_amount: PIPELINE_COST,
  });

  if (error) throw new Error(`reserve_pipeline_credits failed: ${error.message}`);
}

/** Finalizes a successful reservation and records the only actual debit. */
export async function completePipelineCreditReservation(
  supabase: SupabaseClient,
  reservationId: string,
): Promise<void> {
  const { data: completed, error } = await supabase.rpc('complete_pipeline_credit_reservation', {
    p_reservation_id: reservationId,
  });

  if (error) throw new Error(`complete_pipeline_credit_reservation failed: ${error.message}`);
  if (completed !== true) throw new Error('pipeline credit reservation is no longer active');
}

/** Releases a failed run's hold; calling it repeatedly is safe. */
export async function releasePipelineCreditReservation(
  supabase: SupabaseClient,
  reservationId: string,
): Promise<void> {
  const { error } = await supabase.rpc('release_pipeline_credit_reservation', {
    p_reservation_id: reservationId,
  });

  if (error) throw new Error(`release_pipeline_credit_reservation failed: ${error.message}`);
}
