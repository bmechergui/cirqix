/**
 * Adaptateurs Supabase du worker.
 *
 * Le worker écrit avec un client SERVICE-ROLE : il n'agit au nom d'aucune
 * session, il écrit pour le compte du run. RLS ne s'applique donc pas — raison
 * pour laquelle ce processus ne publie aucun port et n'est joignable par
 * personne.
 *
 * La persistance métier réutilise exactement le même magasin que la route web
 * (`PipelineStore`), avec un client différent. Un seul chemin de persistance,
 * donc une seule sémantique de facturation et de provenance.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, PCBStatus } from '@cirqix/types';
import type {
  KicadArtifactName,
  PipelineStore,
  RunEventRow,
  RunEventWriter,
  StoredArtifact,
} from '@cirqix/agents';
import { logger } from '@cirqix/logger';
import type { RunJobContext } from './run-job.js';

export { createPipelineWorker } from '@cirqix/agents/pipeline-queue';
export type { PipelineJobPayload } from '@cirqix/agents';

const log = logger.child({ module: 'worker.adapters' });

const BUCKET = 'kicad-files';
/** Durée de vie des URL signées servies au viewer. */
const SIGNED_URL_TTL_S = 3600;

/**
 * Dépose un artefact KiCad et renvoie une URL signée.
 *
 * Un échec ne doit PAS interrompre le run : le board reste valide sans son
 * aperçu. Perdre 18 minutes de routage parce qu'un upload a échoué serait
 * absurde.
 */
async function uploadArtifact(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
  name: KicadArtifactName,
  content: string,
): Promise<StoredArtifact> {
  const path = `${userId}/${projectId}/${name}`;
  const { error } = await supabase.storage
    .from(BUCKET)
    .upload(path, new Blob([content], { type: 'text/plain' }), { upsert: true });

  if (error) {
    log.warn({ err: error, path }, 'dépôt de l artefact échoué — run poursuivi');
    return {};
  }

  const { data, error: signError } = await supabase.storage
    .from(BUCKET)
    .createSignedUrl(path, SIGNED_URL_TTL_S);

  if (signError) {
    log.warn({ err: signError, path }, 'URL signée indisponible — run poursuivi');
    return {};
  }
  return { signedUrl: data?.signedUrl };
}

/** Magasin de persistance d'un run, côté worker. */
export function createWorkerStore(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
): PipelineStore {
  return {
    uploadArtifact: (name, content) =>
      uploadArtifact(supabase, userId, projectId, name, content),

    async persistProgress(status: PCBStatus, state: PCBState): Promise<void> {
      const { error } = await supabase
        .from('projects')
        .update({
          status,
          pcb_state: state,
          // Pas d'`iteration_count` ici : le compteur n'appartient qu'à la RPC
          // de finalisation, dont la garde `stale_iteration` exige
          // p_iteration_count = iteration_count + 1.
          //
          // Provenance : pipeline réel → board commandable (gate JLCPCB). Elle
          // est posée par l'ADAPTATEUR, jamais par le pipeline.
          agent_mode: 'orchestrator',
          updated_at: new Date().toISOString(),
        })
        .eq('id', projectId);
      if (error) log.warn({ err: error, projectId }, 'persistance intermédiaire échouée');
    },

    async finalizeSuccess(status: PCBStatus, state: PCBState): Promise<void> {
      const { error } = await supabase.rpc('finalize_pipeline_success', {
        p_user_id: userId,
        p_project_id: projectId,
        p_pcb_state: state,
        p_status: status,
        p_agent_mode: 'orchestrator',
      });
      if (error) {
        // Ici, en revanche, on lève : ne pas finaliser signifie ne pas débiter
        // un board pourtant livré et commandable.
        log.error({ err: error, projectId, status }, 'finalisation échouée');
        throw new Error(`finalize_pipeline_success failed: ${error.message}`);
      }
    },
  };
}

/** Journal d'un run — lot d'INSERT, jamais bloquant. */
function createEventWriter(supabase: SupabaseClient, runId: string): RunEventWriter {
  return {
    async insert(rows: RunEventRow[]): Promise<void> {
      if (rows.length === 0) return;
      const { error } = await supabase.from('pcb_run_events').insert(rows);
      if (error) log.error({ err: error, runId }, 'journal du run : insert échoué');
    },
  };
}

/** Assemble le contexte que `runJob` consomme. */
export function createRunEventWriterFactory(supabase: SupabaseClient): RunJobContext {
  return {
    supabase,
    createStore: (userId: string, projectId: string) =>
      createWorkerStore(supabase, userId, projectId),
    createEventWriter: (runId: string) => createEventWriter(supabase, runId),

    async markRunning(runId: string): Promise<void> {
      const { error } = await supabase
        .from('pcb_runs')
        .update({
          status: 'running',
          started_at: new Date().toISOString(),
          heartbeat_at: new Date().toISOString(),
        })
        .eq('id', runId);
      if (error) log.warn({ err: error, runId }, 'passage en running échoué');
    },

    async heartbeat(runId: string): Promise<void> {
      const { error } = await supabase
        .from('pcb_runs')
        .update({ heartbeat_at: new Date().toISOString() })
        .eq('id', runId);
      if (error) log.warn({ err: error, runId }, 'heartbeat échoué');
    },

    async finish(
      runId: string,
      status: 'succeeded' | 'failed' | 'cancelled',
      errorMessage?: string,
    ): Promise<void> {
      const { error } = await supabase
        .from('pcb_runs')
        .update({
          status,
          finished_at: new Date().toISOString(),
          ...(errorMessage ? { error: errorMessage } : {}),
        })
        .eq('id', runId);
      if (error) log.error({ err: error, runId, status }, 'clôture du run échouée');
    },

    async isCancelled(runId: string): Promise<boolean> {
      const { data, error } = await supabase
        .from('pcb_runs')
        .select('cancel_requested')
        .eq('id', runId)
        .single();
      if (error) {
        // Une panne de base ne doit pas ressembler à une annulation : cela
        // interromprait un routage légitime de 20 minutes.
        log.warn({ err: error, runId }, 'lecture d annulation échouée — run poursuivi');
        return false;
      }
      return (data as { cancel_requested: boolean }).cancel_requested === true;
    },
  };
}
