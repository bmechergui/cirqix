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
  runDriver,
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
 * récent est réconcilié en `failed`.
 *
 * ⚠️ Cette phrase se terminait par « ce qui libère aussi sa réservation ».
 * C'ÉTAIT FAUX : `finish()` ne fait qu'un `UPDATE pcb_runs`, et aucun
 * déclencheur ne relie les deux tables. La libération est désormais explicite
 * (`adapters.ts` → `releaseReservationForRun`), donc la phrase est redevenue
 * vraie — mais par le code, pas par la promesse.
 */
export const HEARTBEAT_INTERVAL_MS = 30_000;

export interface RunJobContext {
  supabase: SupabaseClient;
  /**
   * Fabrique le magasin de persistance pour ce run.
   *
   * ⚠️ `agentMode` est la PROVENANCE, et elle vient de `pcb_runs` — jamais du
   * payload du job, jamais d une constante. Elle gouverne le gate de
   * `POST /api/jlcpcb/order`, c est-a-dire une commande reelle et payante.
   */
  createStore: (userId: string, projectId: string, agentMode: string) => PipelineStore;
  /** Relit la provenance enregistree du run. */
  readAgentMode: (runId: string) => Promise<string | null>;
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
  const { runId, projectId, userId, prompt, iterationStart, schema } = payload;

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

  // ⚠️ ECHEC FERME SUR UNE PROVENANCE INCONNUE. Elle decide de la
  // commandabilite du board chez JLCPCB : « inconnu » n est pas « verifie ».
  // Le run est refuse plutot que mene avec une provenance devinee.
  const agentMode = await ctx.readAgentMode(runId);
  if (!agentMode) {
    clearInterval(beat);
    await sink.close();
    await ctx.finish(runId, 'failed', 'provenance introuvable pour ce run');
    log.error({ runId, projectId }, 'provenance introuvable — run refuse');
    return;
  }

  try {
    // ⚠️ La PRESENCE D UN SCHEMA choisit la chaine, et rien d autre.
    //
    // Le solde de l API du modele est epuise depuis le 2026-09-06 :
    // l orchestrateur etant la premiere etape, plus aucun PCB ne peut aboutir
    // par la voie normale. Un schema fourni par le driver contourne ce seul
    // maillon — tout le reste de la chaine est deterministe, et le banc des dix
    // cartes l a mesure jusqu aux Gerbers.
    //
    // ⚠️ Ce choix ne touche PAS a la provenance. `agent_mode` vit dans
    // `pcb_runs`, pose par la route, et le gate JLCPCB exige `orchestrator` :
    // un board du driver reste non commandable, quelle que soit sa qualite.
    const outcome = await runOrchestratorPipeline({
      sink,
      store: ctx.createStore(userId, projectId, agentMode),
      projectId,
      prompt,
      iterationStart,
      // `exactOptionalPropertyTypes` interdit un `undefined` explicite :
      // la propriete est posee, ou elle n existe pas.
      ...(schema ? { source: runDriver({ schema, projectId }) } : {}),
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

