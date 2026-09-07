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

import { extendReservationForRun, releaseReservationForRun } from './reservations.js';
import type { RunJobContext } from './run-job.js';

export { createPipelineWorker } from '@cirqix/agents';
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

/**
 * Magasin de persistance d'un run, côté worker.
 *
 * ⚠️ LA PROVENANCE EST UN PARAMÈTRE, PLUS UNE CONSTANTE. Elle valait
 * `'orchestrator'` en dur, aux deux endroits qui écrivent dans `projects` — ce
 * qui était exact tant que le worker ne savait faire QUE l'orchestrateur.
 *
 * Depuis qu'il sait aussi exécuter la chaîne du driver (`run-driver.ts`), cette
 * constante devenait un mensonge exécutoire : `POST /api/jlcpcb/order` autorise
 * la commande sur `agent_mode = 'orchestrator'`, donc un board dont le schéma a
 * été écrit à la main devenait COMMANDABLE chez JLCPCB. Mesuré le 2026-09-07 sur
 * le premier run du driver : `projet : PCB_LIVRÉ · provenance orchestrator`.
 *
 * Elle est désormais lue dans `pcb_runs.agent_mode`, exactement comme le
 * contrat du job le prescrit : « posée par la ROUTE, relue depuis la base par
 * le worker ». Le payload ne la transporte toujours pas.
 */
export function createWorkerStore(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
  agentMode: string,
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
          // Provenance : celle du RUN, jamais une constante. Voir l'en-tête.
          agent_mode: agentMode,
          updated_at: new Date().toISOString(),
        })
        .eq('id', projectId);
      if (error) log.warn({ err: error, projectId }, 'persistance intermédiaire échouée');
    },

    async finalizeSuccess(status: PCBStatus, state: PCBState): Promise<void> {
      // ⚠️ LES ARGUMENTS NE CORRESPONDAIENT PAS À LA FONCTION. Elle est
      // déclarée `(uuid, uuid, integer, jsonb, text)` depuis la migration 018 :
      // `p_iteration_count`, et PAS de `p_status`. Cet appel envoyait
      // `p_pcb_state, p_status` — Postgres ne trouvait donc aucune surcharge, et
      // TOUT run arrivé jusqu'à `done` échouait à la finalisation, sans débit et
      // sans provenance. Mesuré le 2026-09-07 : « Could not find the function
      // public.finalize_pipeline_success(p_agent_mode, p_pcb_state,
      // p_project_id, p_status, p_user_id) ».
      //
      // Invisible aux tests : ils remplacent le client Supabase par un faux qui
      // accepte n'importe quel objet d'arguments. Un faux plus pauvre que le
      // vrai ne peut pas révéler un contrat rompu — la leçon est déjà inscrite
      // dans CLAUDE.md à propos d'un faux `pcbnew`.
      //
      // `status` reste le statut publié ; l'itération vient de l'état, comme
      // dans l'appel de la route web (`credits.ts`), qui lui était correct.
      const { error } = await supabase.rpc('finalize_pipeline_success', {
        p_user_id: userId,
        p_project_id: projectId,
        p_iteration_count: state.iteration,
        p_pcb_state: { ...state, status },
        p_agent_mode: agentMode,
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
    createStore: (userId: string, projectId: string, agentMode: string) =>
      createWorkerStore(supabase, userId, projectId, agentMode),
    readAgentMode: async (runId: string) => {
      const { data, error } = await supabase
        .from('pcb_runs').select('agent_mode').eq('id', runId).single();
      if (error) {
        log.error({ err: error, runId }, 'provenance illisible');
        return null;
      }
      return (data?.agent_mode as string | undefined) ?? null;
    },
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

      // ⚠️ Le battement prouve que le run VIT : on s'en sert pour repousser
      // l'échéance de sa retenue de crédit. Sans cela, l'échéance est un pari
      // posé au démarrage — trop courte elle libère le crédit sous un job qui
      // tourne, trop longue elle le gèle après un crash. Ici la fenêtre suit le
      // travail réel.
      //
      // `heartbeat_at` était écrit depuis la migration 019 et AUCUN code ne le
      // lisait ; le réconciliateur que deux commentaires annonçaient n'a jamais
      // été écrit. C'est son premier usage.
      await extendReservationForRun(supabase, runId);
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

      // ⚠️ Un run ÉCHOUÉ ou ANNULÉ doit rendre le crédit qu'il retenait. Seuls
      // la route (avant l'enfilement) et `finalize_pipeline_success` (au
      // succès) posaient `released_at` : sur un échec, le crédit restait
      // retenu jusqu'à l'expiration. Supportable à 6 minutes, plus du tout
      // depuis que la retenue couvre la durée du pipeline réel.
      //
      // Au succès, `finalize_pipeline_success` a déjà libéré dans la même
      // transaction que le débit ; l'appel est alors sans effet.
      if (status !== 'succeeded') {
        await releaseReservationForRun(supabase, runId);
      }
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
