/**
 * Exécution d'un job de pipeline par le worker.
 *
 * C'est ici que le plafond tombe. Le même pipeline qu'en route web, mais sans
 * invocation qui l'enserre : un routage peut prendre 20 minutes ou davantage.
 *
 * Les événements ne partent plus dans un flux SSE — le worker n'a aucune
 * connexion vers le navigateur — mais dans `pcb_run_events`, que le client lit
 * en Supabase Realtime. C'est ce qui permet à l'utilisateur de fermer son onglet
 * et de revenir.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import {
  PgSink,
  runOrchestratorPipeline,
  type PipelineJobPayload,
  type PipelineStore,
  type RunEventWriter,
} from '@cirqix/agents';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'worker.run-job' });

/**
 * Cadence du battement de cœur.
 *
 * C'est la SEULE preuve qu'un run vit encore : sans plafond de durée, un job de
 * 30 minutes est indiscernable d'un worker figé. Un run `running` sans battement
 * récent est réconcilié en `failed`, ce qui libère aussi sa réservation.
 */
export const HEARTBEAT_INTERVAL_MS = 30_000;

export interface RunJobContext {
  supabase: SupabaseClient;
  /** Fabrique le magasin de persistance pour ce run. */
  createStore: (userId: string, projectId: string) => PipelineStore;
  /** Écrit les lignes du journal de ce run. */
  createEventWriter: (runId: string) => RunEventWriter;
  markRunning: (runId: string) => Promise<void>;
  heartbeat: (runId: string) => Promise<void>;
  finish: (
    runId: string,
    status: 'succeeded' | 'failed' | 'cancelled',
    error?: string,
  ) => Promise<void>;
  isCancelled: (runId: string) => Promise<boolean>;
}

/**
 * Exécute un job de bout en bout.
 *
 * Le contrat de fin est strict : quoi qu'il arrive, le run est clos et le
 * battement arrêté. Un run laissé `running` bloquerait indéfiniment son projet
 * — l'index unique de la migration 019 refuse un second run vivant.
 */
export async function runJob(
  payload: PipelineJobPayload,
  ctx: RunJobContext,
): Promise<void> {
  const { runId, projectId, userId, prompt, iterationStart } = payload;

  const writer = ctx.createEventWriter(runId);
  const sink = new PgSink(runId, writer);

  await ctx.markRunning(runId);

  // Battement périodique. `unref` n'est pas utilisé : tant qu'un job tourne, le
  // processus doit rester vivant.
  const beat = setInterval(() => {
    void ctx.heartbeat(runId).catch((err: unknown) => {
      log.warn({ err, runId }, 'heartbeat échoué');
    });
  }, HEARTBEAT_INTERVAL_MS);

  try {
    const outcome = await runOrchestratorPipeline({
      sink,
      store: ctx.createStore(userId, projectId),
      projectId,
      prompt,
      iterationStart,
    });

    // Le pipeline ne lève pas sur annulation : il s'arrête simplement de relancer
    // du travail (cf. `RunControl`). C'est donc ici qu'on distingue un run mené à
    // son terme d'un run interrompu par son porteur.
    const cancelled = await ctx.isCancelled(runId);
    await sink.close();

    if (cancelled) {
      // Un run annulé n'est pas un run raté : l'utilisateur a décidé d'arrêter.
      await ctx.finish(runId, 'cancelled');
      log.info({ runId, projectId, cancelled: true }, 'run terminé');
    } else if (!outcome.ok) {
      // ⚠️ « Ne pas lever » ne veut pas dire « avoir réussi ». Le pipeline émet
      // les erreurs métier au journal et rend la main — sans quoi une erreur
      // n'atteindrait jamais l'utilisateur. On en déduisait `succeeded`.
      //
      // Mesuré le 2026-08-21 sur un run RÉEL : 126 événements, dernier
      // `kind=error` (« non-billable state: ROUTING_DONE »), et le run
      // enregistré `succeeded`. Le board n'était ni DRC-clean ni livré.
      await ctx.finish(runId, 'failed', outcome.error);
      log.warn({ runId, projectId, err: outcome.error }, 'run terminé en erreur');
    } else {
      await ctx.finish(runId, 'succeeded');
      log.info({ runId, projectId, cancelled: false }, 'run terminé');
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'pipeline failed';
    // Le journal doit porter la cause : c'est tout ce que l'utilisateur verra,
    // le flux SSE n'existant plus pour la transmettre.
    await sink.emit({ type: 'error', message }).catch(() => undefined);
    await sink.close().catch(() => undefined);
    await ctx.finish(runId, 'failed', message);
    log.error({ err, runId, projectId }, 'run échoué');
    throw err;
  } finally {
    clearInterval(beat);
  }
}

