import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState } from '@cirqix/types';
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

/**
 * Le repli local ne doit s'armer que pour UNE cause : le compte Anthropic n'a
 * plus de quota. Il enchaîne un pipeline tronqué (5 étapes sur 8) qu'il persiste
 * ensuite avec `agent_mode: 'orchestrator'` — la provenance qu'exige le gate
 * JLCPCB. L'armer par erreur revient donc à rendre commandable un board qui n'a
 * ni footprints résolus, ni PCB généré nativement, ni export.
 *
 * L'ancien test — `message.includes('credit') || message.includes('402')` — le
 * déclenchait sur n'importe quelle erreur dont le message contient « credit » :
 * une erreur Supabase mentionnant la table `credits` suffisait, alors qu'elle n'a
 * aucun rapport avec un quota Anthropic. On exige désormais la signature réelle
 * de l'erreur de quota : le statut HTTP 402 du SDK, ou le message exact renvoyé
 * par l'API Anthropic.
 */
export function shouldFallbackToLocalPipeline(error: unknown): boolean {
  if (error instanceof CreditDeductionError) {
    return false;
  }
  if (typeof error === 'object' && error !== null && 'status' in error) {
    if ((error as { status?: unknown }).status === 402) return true;
  }
  const message = error instanceof Error ? error.message : String(error);
  return /credit balance is too low/i.test(message);
}

// `deductPipelineCost` a été SUPPRIMÉE ici. Elle débitait PIPELINE_COST via
// `deduct_credits`, n'était appelée par aucun code de production (uniquement par
// ses propres tests), et faisait doublon avec `finalize_pipeline_success`, qui
// débite déjà ce même montant en interne. Un futur appelant — son nom y invitait —
// aurait facturé 17 crédits pour un seul pipeline. La facturation du pipeline
// passe par `finalizePipelineSuccess` et par elle seule.

/** Charge one completed iteration and publish its final state atomically. */
export async function finalizePipelineSuccess(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
  state: PCBState,
  agentMode: 'orchestrator' | 'simulator',
): Promise<void> {
  if (state.status !== 'DRC_CLEAN' || !Number.isInteger(state.iteration) || state.iteration < 1) {
    throw new CreditDeductionError('invalid final pipeline state');
  }

  const { data, error } = await supabase.rpc('finalize_pipeline_success', {
    p_user_id: userId,
    p_project_id: projectId,
    p_iteration_count: state.iteration,
    p_pcb_state: state,
    p_agent_mode: agentMode,
  });

  if (error) {
    log.error({ err: error, userId, projectId }, 'finalize_pipeline_success RPC failed');
    throw new CreditDeductionError(error);
  }
  if (data !== true) {
    throw new CreditDeductionError('pipeline iteration was already finalized');
  }
}
