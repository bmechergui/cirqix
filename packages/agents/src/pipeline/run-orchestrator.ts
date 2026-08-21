/**
 * Exécution d'un run par l'orchestrateur — indépendante de son porteur.
 *
 * Ce code vivait dans `apps/web/src/app/api/agent/lib/orchestrator-bridge.ts`,
 * où il dépendait de Supabase et du flux SSE de Next. Ces deux liens le clouaient
 * à l'invocation web, plafonnée à 300 s, alors qu'un routage complexe demande
 * 900 s et davantage.
 *
 * Il ne connaît désormais que deux interfaces :
 *   - `RunSink`       — où vont les événements (SSE aujourd'hui, journal
 *                       Postgres dans le worker) ;
 *   - `PipelineStore` — qui persiste (adaptateur fourni par le porteur).
 *
 * Le comportement est INCHANGÉ, gardes de facturation comprises. C'est un
 * déplacement, pas une réécriture.
 */

import type { PCBState, PCBStatus, SimulationData } from '@cirqix/types';
import { runOrchestrator } from '../orchestrator';
import type { RunSink } from './run-sink';
import type { PipelineStore } from './store';

/** Étapes qui apparaissent dans la Timeline (SPEC est interne). */
type UiStep = 'SCHEMA' | 'ERC' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT';

/**
 * Issue d'un run, telle que le PORTEUR doit la comprendre.
 *
 * ⚠️ Le pipeline ne LÈVE pas sur une erreur non liée aux crédits : il l'émet au
 * journal et rend la main — c'est voulu, une erreur métier doit atteindre
 * l'utilisateur sans tuer le porteur. Mais « ne pas lever » ne veut pas dire
 * « avoir réussi », et le worker en déduisait `succeeded`.
 *
 * Mesuré le 2026-08-21 sur un run RÉEL en base de production : 126 événements,
 * dernier `kind=error` (« non-billable state: ROUTING_DONE »), et
 * `pcb_runs.status = 'succeeded'`. Le board n'était ni DRC-clean ni livré, et
 * le dernier message à l'utilisateur était une erreur — toute réconciliation
 * l'aurait compté comme une réussite.
 *
 * L'issue est donc RENVOYÉE, plus déduite d'une absence d'exception.
 * Garde : services/worker/src/tests/run-job.test.ts.
 */
export type RunOutcome = { ok: true } | { ok: false; error: string };

export interface RunPipelineOptions {
  sink: RunSink;
  store: PipelineStore;
  projectId: string;
  prompt: string;
  iterationStart: number;
}

type OrchestratorPcbState = Record<string, unknown> & {
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
  pcb_status?: PCBStatus;
};

/** Une erreur de crédit doit remonter pour armer le repli du porteur. */
function isCreditFailure(message: string): boolean {
  return message.includes('credit') || message.includes('402');
}

export async function runOrchestratorPipeline(
  opts: RunPipelineOptions,
): Promise<RunOutcome> {
  const { sink, store, projectId, prompt, iterationStart } = opts;

  let mergedState: Partial<PCBState> = {
    projectId,
    iteration: iterationStart + 1,
    status: 'INITIAL',
  };
  let lastStatus: PCBStatus = 'INITIAL';

  try {
    for await (const ev of runOrchestrator({ userMessage: prompt, projectId, history: [] })) {
      switch (ev.type) {
        case 'text':
          await sink.emit({ type: 'token', content: ev.delta });
          break;

        case 'step': {
          const validSteps: UiStep[] = ['SCHEMA', 'ERC', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT'];
          if (validSteps.includes(ev.step as UiStep)) {
            await sink.emit({ type: 'step', step: ev.step as UiStep });
          }
          break;
        }

        case 'reasoning':
          await sink.emit({ type: 'reasoning', steps: ev.steps });
          break;

        case 'pcb_state': {
          const raw = ev.state as OrchestratorPcbState;

          let kicadSchUrl: string | undefined;
          let kicadPcbUrl: string | undefined;
          if (typeof raw.kicad_sch_content === 'string' && raw.kicad_sch_content.length > 0) {
            const up = await store.uploadArtifact('schematic.kicad_sch', raw.kicad_sch_content);
            if (up.signedUrl) kicadSchUrl = up.signedUrl;
          }
          if (typeof raw.kicad_pcb_content === 'string' && raw.kicad_pcb_content.length > 0) {
            // On dépose ce que l'outil a produit. Re-placer ici déplacerait des
            // footprints APRÈS que le routage a posé le cuivre, déconnectant les
            // pads : placement et routage appartiennent à leurs handlers.
            const up = await store.uploadArtifact('pcb.kicad_pcb', raw.kicad_pcb_content);
            if (up.signedUrl) kicadPcbUrl = up.signedUrl;
          }

          // Fusion incrémentale : l'UI garde les champs antérieurs (composants,
          // nets…) quand un événement tardif ne renvoie que des deltas.
          const rawWithoutContent: Record<string, unknown> = { ...raw };
          delete rawWithoutContent['kicad_sch_content'];
          delete rawWithoutContent['kicad_pcb_content'];

          const status: PCBStatus = (raw.pcb_status as PCBStatus | undefined) ?? lastStatus;
          mergedState = {
            ...mergedState,
            ...rawWithoutContent,
            projectId,
            status,
            iteration: mergedState.iteration ?? iterationStart + 1,
          } as Partial<PCBState>;
          if (kicadSchUrl) (mergedState as PCBState).kicad_sch_url = kicadSchUrl;
          if (kicadPcbUrl) (mergedState as PCBState).kicad_pcb_url = kicadPcbUrl;

          const r = raw as Record<string, unknown>;
          if (typeof r['zip_b64'] === 'string') (mergedState as PCBState).gerberZipB64 = r['zip_b64'];
          if (typeof r['bom_csv'] === 'string') (mergedState as PCBState).bomCsv = r['bom_csv'];
          if (typeof r['quote_usd'] === 'number') (mergedState as PCBState).quoteUsd = r['quote_usd'];
          if (typeof r['lead_time_days'] === 'number') {
            (mergedState as PCBState).leadTimeDays = r['lead_time_days'];
          }
          if (r['simulation_data'] && typeof r['simulation_data'] === 'object') {
            (mergedState as PCBState).simulationData = r['simulation_data'] as SimulationData;
          }

          lastStatus = status;

          const finalized = mergedState as PCBState;
          if (status === 'DRC_CLEAN') break;

          await sink.emit({ type: 'pcb_state', state: finalized });
          await sink.emit({ type: 'status', status });
          await store.persistProgress(status, finalized);
          break;
        }

        case 'tool_result':
          // Les blobs KiCad ne partent pas au client : `text` et `pcb_state`
          // couvrent l'affichage.
          break;

        case 'error':
          if (isCreditFailure(ev.message)) throw new Error(ev.message);
          await sink.emit({ type: 'error', message: ev.message });
          break;

        case 'done':
          // Deux états terminaux facturables, pas un seul.
          //
          // `prompts.ts` fait enchaîner l'export APRÈS le DRC : un pipeline qui
          // réussit complètement finit donc en `PCB_LIVRÉ`, pas en `DRC_CLEAN`.
          // La garde n'acceptait que `DRC_CLEAN` et levait sur le chemin
          // nominal ; le `catch` de fin avalait l'exception (elle ne contient ni
          // « credit » ni « 402 »), si bien que le run se terminait
          // « normalement » sans jamais finaliser. Aucun débit, alors que le
          // board, ses Gerbers et la provenance venaient d'être persistés et que
          // le gate JLCPCB accepte `PCB_LIVRÉ` : un PCB fabricable, commandable
          // et gratuit.
          //
          // `PCB_LIVRÉ` n'affaiblit pas la garde, il la renforce : `handleExport`
          // ne l'émet QUE si `drc_clean` est vrai en cache — donc après un DRC
          // réellement exécuté et réellement propre. État strictement plus
          // avancé que `DRC_CLEAN`.
          //
          // Trouvé le 2026-08-12 par deux audits externes indépendants.
          if (lastStatus !== 'DRC_CLEAN' && lastStatus !== 'PCB_LIVRÉ') {
            throw new Error(`Orchestrator completed in a non-billable state: ${lastStatus}`);
          }
          // On publie `lastStatus`, pas un `DRC_CLEAN` codé en dur : rétrograder
          // un run allé jusqu'à l'export ferait reculer le projet aux yeux de
          // l'utilisateur, alors qu'il est plus avancé.
          await store.finalizeSuccess(lastStatus, mergedState as PCBState);
          await sink.emit({ type: 'step', step: null });
          await sink.emit({ type: 'pcb_state', state: mergedState as PCBState });
          await sink.emit({ type: 'status', status: lastStatus });
          await sink.emit({ type: 'done' });
          break;

        case 'iteration':
        case 'tool_call':
        default:
          break;
      }
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Orchestrator failed';
    // Remonte au porteur : c'est lui qui décide d'armer le repli local.
    if (isCreditFailure(message)) throw err;
    await sink.emit({ type: 'error', message });
    return { ok: false, error: message };
  }

  return { ok: true };
}
