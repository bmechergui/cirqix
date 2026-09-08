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
 * Durée de vie d'une retenue, en secondes.
 *
 * ⚠️ VALAIT 360 s JUSQU'AU 2026-09-05, calibré sur `maxDuration = 300` de la
 * route SYNCHRONE. Le pipeline ASYNCHRONE, lui, dure **19 minutes mesurées**
 * (run `4290007c`) : passé la sixième, la retenue expirait alors que le job
 * tournait encore. `available_credits` cesse alors de la compter, un second
 * projet démarre sur le même solde, et les deux consomment le modèle et le
 * service KiCad sans que rien ne soit engagé — exactement la fenêtre que la
 * migration `015_credit_reservations.sql` a été écrite pour fermer.
 *
 * Le solde ne peut pas devenir négatif (contrainte `credits_balance_nonnegative`),
 * donc ce n'est pas un vol de crédits : c'est de la ressource brûlée, et un
 * second run qui échoue à la facturation après vingt minutes de travail.
 *
 * Relevé par Grok en consultation, vérifié ligne à ligne.
 *
 * ⚠️ Une heure est le PLAFOND accepté par `reserve_pipeline_credits`
 * (`1..3600`). Aller au-delà demanderait une migration.
 *
 * ⚠️ Allonger cette durée n'était PAS sans risque : le worker ne libérait rien
 * sur échec, malgré un commentaire de `run-job.ts` qui l'affirmait. Un seul run
 * raté aurait gelé le solde une heure. C'est corrigé dans le même lot
 * (`services/worker/src/reservations.ts`) — les deux vont ensemble.
 */
export const PIPELINE_RESERVATION_TTL_S = 3600;

/** Le solde ne couvre pas un pipeline de plus — l'appelant doit répondre 402. */
export class InsufficientCreditsError extends Error {
  constructor() {
    super('Insufficient credits');
    this.name = 'InsufficientCreditsError';
  }
}

/**
 * Un pipeline tourne déjà sur ce projet — l'appelant doit répondre 409.
 *
 * Ce n'est ni un manque de crédits ni une panne : deux pipelines sur un même
 * projet se disputeraient `iteration_count` et le second échouerait de toute
 * façon. Le cas courant est un double-clic ou un réessai après timeout.
 */
export class PipelineAlreadyRunningError extends Error {
  constructor() {
    super('A pipeline is already running for this project');
    this.name = 'PipelineAlreadyRunningError';
  }
}

/** Toute autre défaillance de la réservation — l'appelant doit répondre 500. */
export class CreditReservationError extends Error {
  constructor(cause: unknown) {
    super('Credit reservation failed', { cause });
    this.name = 'CreditReservationError';
  }
}

function isPostgresError(error: unknown): error is { code?: string; message?: string } {
  return typeof error === 'object' && error !== null;
}

/**
 * Engage `PIPELINE_COST` avant de lancer le pipeline et renvoie l'identifiant
 * de la retenue.
 *
 * La garantie est en base : la RPC verrouille la ligne `credits` du porteur,
 * de sorte que deux démarrages concurrents ne peuvent plus lire le même solde
 * et se croire tous deux finançables.
 */
export async function reservePipelineCredits(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
): Promise<string> {
  const { data, error } = await supabase.rpc('reserve_pipeline_credits', {
    p_user_id: userId,
    p_project_id: projectId,
    p_amount: PIPELINE_COST,
    p_ttl_seconds: PIPELINE_RESERVATION_TTL_S,
  });

  if (error) {
    // `insufficient_credits` et `invalid_project` portent le MÊME SQLSTATE
    // (22023). Se fier au code seul répondrait « crédits insuffisants » à une
    // tentative d'utiliser le projet d'autrui : un refus de sécurité déguisé en
    // problème de facturation, invisible en supervision.
    const message = isPostgresError(error) ? (error.message ?? '') : '';
    if (/insufficient_credits/.test(message)) {
      log.info({ userId, projectId }, 'pipeline refusé : solde insuffisant');
      throw new InsufficientCreditsError();
    }
    if (/pipeline_already_running/.test(message)) {
      log.info({ userId, projectId }, 'pipeline refusé : un run est déjà en cours');
      throw new PipelineAlreadyRunningError();
    }
    log.error({ err: error, userId, projectId }, 'reserve_pipeline_credits RPC failed');
    throw new CreditReservationError(error);
  }

  if (typeof data !== 'string' || data.length === 0) {
    // Sans identifiant il n'y a rien à libérer : la retenue resterait posée
    // jusqu'à expiration alors que le pipeline n'a jamais démarré.
    throw new CreditReservationError('reserve_pipeline_credits returned no reservation id');
  }

  return data;
}

/**
 * Lève la retenue. Appelée depuis un `finally` : elle ne jette jamais, sous
 * peine de masquer l'erreur réelle du pipeline. Le TTL en base reste le filet
 * — une retenue non libérée cesse de compter d'elle-même.
 */
export async function releasePipelineReservation(
  supabase: SupabaseClient,
  reservationId: string,
): Promise<void> {
  try {
    const { error } = await supabase.rpc('release_pipeline_reservation', {
      p_reservation_id: reservationId,
    });
    if (error) {
      log.error({ err: error, reservationId }, 'release_pipeline_reservation RPC failed');
    }
  } catch (err) {
    log.error({ err, reservationId }, 'release_pipeline_reservation threw');
  }
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
  // Trois provenances distinctes (migration 018) :
  //   orchestrator   — pipeline complet, SEUL facturé et SEUL commandable ;
  //   local_fallback — vrais handlers, mais footprint/gen_pcb/export sautés ;
  //   simulator      — états fabriqués.
  // Seul `orchestrator` déclenche le débit, côté RPC.
  agentMode: 'orchestrator' | 'simulator' | 'local_fallback',
): Promise<void> {
  // Deux états terminaux facturables. `PCB_LIVRÉ` est strictement plus avancé
  // que `DRC_CLEAN` : `handleExport` ne l'émet QUE si `drc_clean` est vrai en
  // cache, donc après un DRC réellement exécuté et propre. N'accepter que
  // `DRC_CLEAN` refusait de facturer les pipelines les plus complets — ceux qui
  // vont jusqu'aux Gerbers (issue trouvée le 2026-08-12).
  const BILLABLE_FINAL_STATUSES = ['DRC_CLEAN', 'PCB_LIVRÉ'] as const;
  if (
    !BILLABLE_FINAL_STATUSES.includes(state.status as (typeof BILLABLE_FINAL_STATUSES)[number]) ||
    !Number.isInteger(state.iteration) ||
    state.iteration < 1
  ) {
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
