import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, PCBStatus, SimulationData } from '@cirqix/types';
import { runOrchestrator } from '@cirqix/agents';
import { logger } from '@cirqix/logger';
import { encodeSse } from './sse';
import { uploadKicadArtifact } from './kicad-storage';
import { finalizePipelineSuccess } from './credits';
import type { RunSink } from '@cirqix/agents';

const log = logger.child({ module: 'orchestrator-bridge' });

// Only the steps that surface in the UI Timeline (SPEC is skipped — it's
// internal context analysis without a dedicated stage).
type UiStep = 'SCHEMA' | 'ERC' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT';

interface BridgeOptions {
  sink: RunSink;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
}

type OrchestratorPcbState = Record<string, unknown> & {
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
  pcb_status?: PCBStatus;
};

export async function runRealOrchestrator(opts: BridgeOptions): Promise<void> {
  const { sink, supabase, userId, projectId, prompt, iterationStart } = opts;

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
          // Actions du reasoner IA (déblocage routage) → affichage temps-réel UI
          await sink.emit({ type: 'reasoning', steps: ev.steps });
          break;

        case 'pcb_state': {
          const raw = ev.state as OrchestratorPcbState;

          log.debug(
            {
              has_sch: typeof raw.kicad_sch_content === 'string' ? raw.kicad_sch_content.length : false,
              has_pcb: typeof raw.kicad_pcb_content === 'string' ? raw.kicad_pcb_content.length : false,
              status: raw.pcb_status ?? 'undefined',
            },
            'pcb_state event',
          );

          // Upload KiCad artifacts (if present) and inject signed URLs
          let kicad_sch_url: string | undefined;
          let kicad_pcb_url: string | undefined;
          if (typeof raw.kicad_sch_content === 'string' && raw.kicad_sch_content.length > 0) {
            const up = await uploadKicadArtifact(
              supabase, userId, projectId, 'schematic.kicad_sch', raw.kicad_sch_content,
            );
            if (up.signedUrl) kicad_sch_url = up.signedUrl;
          }
          if (typeof raw.kicad_pcb_content === 'string' && raw.kicad_pcb_content.length > 0) {
            // Upload whatever the agent tool produced — placement/routing are handled
            // exclusively by call_agent_placement and call_agent_routing in tools.ts.
            // Re-placing here would move footprints AFTER Freerouting laid traces,
            // disconnecting pads from copper.
            const up = await uploadKicadArtifact(
              supabase, userId, projectId, 'pcb.kicad_pcb', raw.kicad_pcb_content,
            );
            if (up.signedUrl) kicad_pcb_url = up.signedUrl;
          }

          // Merge incrementally so the UI keeps prior fields (components, nets, …)
          // when later events return only deltas.
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
          if (kicad_sch_url) (mergedState as PCBState).kicad_sch_url = kicad_sch_url;
          if (kicad_pcb_url) (mergedState as PCBState).kicad_pcb_url = kicad_pcb_url;

          // Map export tool result fields (snake_case) → PCBState (camelCase)
          const r = raw as Record<string, unknown>;
          if (typeof r['zip_b64'] === 'string') (mergedState as PCBState).gerberZipB64 = r['zip_b64'];
          if (typeof r['bom_csv'] === 'string') (mergedState as PCBState).bomCsv = r['bom_csv'];
          if (typeof r['quote_usd'] === 'number') (mergedState as PCBState).quoteUsd = r['quote_usd'];
          if (typeof r['lead_time_days'] === 'number') (mergedState as PCBState).leadTimeDays = r['lead_time_days'];
          if (r['simulation_data'] && typeof r['simulation_data'] === 'object') {
            (mergedState as PCBState).simulationData = r['simulation_data'] as SimulationData;
          }

          lastStatus = status;

          const finalized = mergedState as PCBState;
          if (status === 'DRC_CLEAN') {
            break;
          }
          await sink.emit({ type: 'pcb_state', state: finalized });
          await sink.emit({ type: 'status', status });

          // Persist to DB (best-effort)
          await supabase
            .from('projects')
            .update({
              status,
              pcb_state: finalized,
              // Pas d'`iteration_count` ici : `iteration` vaut iterationStart + 1
              // pendant tout le run, donc l'écrire dès une étape intermédiaire
              // ferait échouer la garde `stale_iteration` de
              // finalize_pipeline_success (qui exige p_iteration_count =
              // iteration_count + 1). Le compteur n'appartient qu'à la RPC de
              // finalisation. Garde : orchestrator-bridge.test.ts.
              // Provenance : pipeline réel → board commandable (gate JLCPCB).
              agent_mode: 'orchestrator',
              updated_at: new Date().toISOString(),
            })
            .eq('id', projectId);
          break;
        }

        case 'tool_result':
          // Drop noisy tool_result blobs from the client stream — text and pcb_state cover the UX.
          break;

        case 'error':
          if (ev.message.includes('credit') || ev.message.includes('402')) {
            throw new Error(ev.message); // Throw to trigger fallback
          }
          await sink.emit({ type: 'error', message: ev.message });
          break;

        case 'done':
          // Deux états terminaux facturables, pas un seul.
          //
          // `prompts.ts` fait enchaîner l'export APRÈS le DRC : un pipeline qui
          // réussit complètement finit donc en `PCB_LIVRÉ`, pas en `DRC_CLEAN`.
          // La garde n'acceptait que `DRC_CLEAN` et levait sur le chemin
          // nominal ; le `catch` de fin avalait l'exception (elle ne contient
          // ni « credit » ni « 402 »), si bien que le run se terminait
          // « normalement » en affichant une erreur — et surtout sans jamais
          // appeler `finalizePipelineSuccess`. Aucun débit, alors que le board,
          // ses Gerbers et `agent_mode: 'orchestrator'` venaient d'être
          // persistés et que le gate JLCPCB accepte `PCB_LIVRÉ` : un PCB
          // fabricable, commandable et gratuit.
          //
          // `PCB_LIVRÉ` n'affaiblit pas la garde, il la renforce :
          // `handleExport` ne l'émet QUE si `drc_clean` est vrai en cache,
          // c'est-à-dire après un DRC réellement exécuté et réellement propre.
          // C'est un état strictement plus avancé que `DRC_CLEAN`.
          //
          // Trouvé le 2026-08-12 par deux audits externes indépendants.
          if (lastStatus !== 'DRC_CLEAN' && lastStatus !== 'PCB_LIVRÉ') {
            throw new Error(`Orchestrator completed in a non-billable state: ${lastStatus}`);
          }
          // Débit et publication de l'état atteint, en une transaction
          // service-role. On publie `lastStatus` et non un `DRC_CLEAN` codé en
          // dur : rétrograder un run allé jusqu'à l'export ferait « reculer »
          // le projet aux yeux de l'utilisateur, alors qu'il est plus avancé.
          await finalizePipelineSuccess(
            supabase,
            userId,
            projectId,
            mergedState as PCBState,
            'orchestrator',
          );
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
    if (message.includes('credit') || message.includes('402')) {
      throw err; // Re-throw to trigger fallback in route.ts
    }
    await sink.emit({ type: 'error', message });
  }
}
