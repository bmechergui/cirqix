/**
 * Libération de la retenue de crédit d'un run terminé.
 *
 * ⚠️ CONSTAT DU 2026-09-05. Le commentaire de `run-job.ts` affirmait qu'un run
 * réconcilié en `failed` « libère aussi sa réservation ». C'était FAUX :
 * `finish()` ne fait qu'un `UPDATE pcb_runs`, et aucun déclencheur ne relie les
 * deux tables. Seuls la route — avant l'enfilement — et
 * `finalize_pipeline_success` — au succès — posaient `released_at`.
 *
 * Sur un run échoué ou annulé, le crédit restait donc retenu jusqu'à
 * l'expiration. Supportable tant que la retenue durait 6 minutes ; plus du tout
 * dès qu'on l'aligne sur la durée du pipeline réel, sinon un seul échec gèle le
 * solde une heure.
 *
 * Le lien nécessaire existait déjà : `pcb_runs.reservation_id` (migration 019)
 * est renseigné à la création du run.
 *
 * Garde : `tests/liberation-reservation.test.ts`.
 */
import type { SupabaseClient } from '@supabase/supabase-js';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'worker.reservations' });

/**
 * Durée demandée à chaque prolongation, en secondes.
 *
 * Le battement de cœur tombe toutes les 30 s : cette valeur n'a donc pas à
 * couvrir la durée du pipeline, seulement à survivre à quelques battements
 * manqués (base momentanément indisponible, worker occupé). Dix minutes en
 * laissent passer une vingtaine.
 *
 * ⚠️ C'est ce qui rend la fenêtre GLISSANTE : un run vivant garde son crédit
 * engagé aussi longtemps qu'il travaille, un run mort cesse d'être rafraîchi et
 * sa retenue expire d'elle-même — sans attendre l'heure de l'échéance initiale.
 */
export const RESERVATION_TTL_S = 600;

/** Identifiant de la retenue portée par ce run, ou `null`. */
async function reservationDuRun(
  supabase: SupabaseClient,
  runId: string,
): Promise<string | null> {
  const { data, error } = await supabase
    .from('pcb_runs')
    .select('reservation_id')
    .eq('id', runId)
    .maybeSingle();

  if (error) {
    log.error({ err: error, runId }, 'retenue du run non lue');
    return null;
  }
  return (data as { reservation_id?: string | null } | null)?.reservation_id ?? null;
}

/**
 * Repousse l'échéance de la retenue, sur preuve que le run vit.
 *
 * ⚠️ N'échoue JAMAIS, et surtout pas quand la fonction n'existe pas en base :
 * la migration `021` peut ne pas être appliquée. Le comportement retombe alors
 * sur l'échéance fixe, ce qui est exactement l'état d'avant — mais le battement
 * de cœur, lui, doit continuer : c'est la seule preuve qu'un run de vingt
 * minutes est encore vivant.
 */
export async function extendReservationForRun(
  supabase: SupabaseClient,
  runId: string,
): Promise<void> {
  try {
    const reservationId = await reservationDuRun(supabase, runId);
    if (!reservationId) return;

    const { error } = await supabase.rpc('extend_pipeline_reservation', {
      p_reservation_id: reservationId,
      p_ttl_seconds: RESERVATION_TTL_S,
    });
    if (error) {
      log.warn({ err: error, runId, reservationId }, 'retenue non prolongée');
    }
  } catch (err) {
    log.warn({ err, runId }, 'prolongation de la retenue a levé');
  }
}

/**
 * Rend le crédit retenu par `runId`, si ce run en retenait un.
 *
 * ⚠️ N'échoue JAMAIS. La clôture du run est ce qui compte : un crédit retenu
 * finit de toute façon par expirer, tandis qu'un run laissé `running` serait
 * réconcilié à tort et bloquerait son projet. On journalise et on rend la main.
 */
export async function releaseReservationForRun(
  supabase: SupabaseClient,
  runId: string,
): Promise<void> {
  try {
    // Cas normal d'un `null` : le mode simulateur ne facture pas, donc ne
    // retient rien.
    const reservationId = await reservationDuRun(supabase, runId);
    if (!reservationId) return;

    const { error: rpcError } = await supabase.rpc('release_pipeline_reservation', {
      p_reservation_id: reservationId,
    });
    if (rpcError) {
      log.error({ err: rpcError, runId, reservationId }, 'libération de la retenue échouée');
    }
  } catch (err) {
    log.error({ err, runId }, 'libération de la retenue a levé');
  }
}
