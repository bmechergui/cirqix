/**
 * Adaptateur Supabase du pipeline orchestrateur.
 *
 * Le pipeline lui-même vit désormais dans
 * `packages/agents/src/pipeline/run-orchestrator.ts` : il ne connaît ni Supabase
 * ni le flux SSE de Next, ce qui lui permet de tourner aussi bien ici que dans
 * le worker persistant — hors de l'invocation plafonnée à 300 s.
 *
 * Ce fichier ne fait plus qu'une chose : brancher ce pipeline sur Supabase. Sa
 * signature est INCHANGÉE, pour que les appelants et les tests existants
 * n'aient pas à bouger.
 *
 * ⚠️ La provenance `'orchestrator'` est posée ICI, par l'adaptateur, et n'est
 * plus un paramètre du pipeline. Elle gouverne le gate de
 * `POST /api/jlcpcb/order` — une commande réelle et payante — donc seul le
 * porteur, qui sait quel chemin il a choisi d'exécuter, a le droit de la
 * déclarer. Un bug dans le pipeline ne peut plus promouvoir un repli en run
 * commandable.
 */

import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, PCBStatus } from '@cirqix/types';
import type {
  KicadArtifactName,
  PipelineStore,
  RunSink,
  StoredArtifact,
} from '@cirqix/agents';
import { runOrchestratorPipeline } from '@cirqix/agents';
import { logger } from '@cirqix/logger';
import { uploadKicadArtifact } from './kicad-storage';
import { finalizePipelineSuccess } from './credits';

const log = logger.child({ module: 'orchestrator-bridge' });

interface BridgeOptions {
  sink: RunSink;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
}

/**
 * Construit le magasin Supabase d'un run.
 *
 * Exporté pour que le worker puisse le réutiliser tel quel : c'est exactement la
 * même persistance, avec un client service-role au lieu du client de requête.
 */
export function createSupabaseStore(
  supabase: SupabaseClient,
  userId: string,
  projectId: string,
): PipelineStore {
  return {
    async uploadArtifact(name: KicadArtifactName, content: string): Promise<StoredArtifact> {
      const up = await uploadKicadArtifact(supabase, userId, projectId, name, content);
      return { signedUrl: up.signedUrl ?? undefined };
    },

    async persistProgress(status: PCBStatus, state: PCBState): Promise<void> {
      const { error } = await supabase
        .from('projects')
        .update({
          status,
          pcb_state: state,
          // Pas d'`iteration_count` ici : `iteration` vaut iterationStart + 1
          // pendant tout le run, donc l'écrire dès une étape intermédiaire ferait
          // échouer la garde `stale_iteration` de `finalize_pipeline_success`
          // (qui exige p_iteration_count = iteration_count + 1). Le compteur
          // n'appartient qu'à la RPC de finalisation.
          // Garde : orchestrator-bridge.test.ts.
          //
          // Provenance : pipeline réel → board commandable (gate JLCPCB).
          agent_mode: 'orchestrator',
          updated_at: new Date().toISOString(),
        })
        .eq('id', projectId);
      if (error) log.warn({ err: error, projectId }, 'persistance intermédiaire échouée');
    },

    async finalizeSuccess(status: PCBStatus, state: PCBState): Promise<void> {
      await finalizePipelineSuccess(supabase, userId, projectId, state, 'orchestrator');
      log.debug({ projectId, status }, 'run finalisé');
    },
  };
}

export async function runRealOrchestrator(opts: BridgeOptions): Promise<void> {
  const { sink, supabase, userId, projectId, prompt, iterationStart } = opts;

  await runOrchestratorPipeline({
    sink,
    store: createSupabaseStore(supabase, userId, projectId),
    projectId,
    prompt,
    iterationStart,
  });
}
