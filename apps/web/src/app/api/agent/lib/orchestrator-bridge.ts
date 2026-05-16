import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, PCBStatus } from '@layrix/types';
import { runOrchestrator } from '@layrix/agents';
import { encodeSse } from './sse';
import { uploadKicadArtifact } from './kicad-storage';

// Only the steps that surface in the UI Timeline (SPEC is skipped — it's
// internal context analysis without a dedicated stage).
type UiStep = 'SCHEMA' | 'ERC' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT';

interface BridgeOptions {
  controller: ReadableStreamDefaultController<Uint8Array>;
  encoder: TextEncoder;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
  balanceStart: number;
}

type OrchestratorPcbState = Record<string, unknown> & {
  kicad_sch_content?: string;
  kicad_pcb_content?: string;
  pcb_status?: PCBStatus;
};

export async function runRealOrchestrator(opts: BridgeOptions): Promise<void> {
  const { controller, encoder, supabase, userId, projectId, prompt, iterationStart, balanceStart } = opts;

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
          controller.enqueue(encoder.encode(encodeSse({ type: 'token', content: ev.delta })));
          break;

        case 'step': {
          const validSteps: UiStep[] = ['SCHEMA', 'ERC', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT'];
          if (validSteps.includes(ev.step as UiStep)) {
            controller.enqueue(
              encoder.encode(encodeSse({ type: 'step', step: ev.step as UiStep }))
            );
          }
          break;
        }

        case 'pcb_state': {
          const raw = ev.state as OrchestratorPcbState;

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
          lastStatus = status;

          const finalized = mergedState as PCBState;
          controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: finalized })));
          controller.enqueue(encoder.encode(encodeSse({ type: 'status', status })));

          // Persist to DB (best-effort)
          await supabase
            .from('projects')
            .update({
              status,
              pcb_state: finalized,
              iteration_count: finalized.iteration,
              updated_at: new Date().toISOString(),
            })
            .eq('id', projectId);
          break;
        }

        case 'tool_result':
          // Drop noisy tool_result blobs from the client stream — text and pcb_state cover the UX.
          break;

        case 'error':
          controller.enqueue(encoder.encode(encodeSse({ type: 'error', message: ev.message })));
          break;

        case 'done':
          controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: null })));
          // Deduct credits — same fixed cost as simulator until per-step billing is wired
          await supabase
            .from('credits')
            .update({
              balance: Math.max(0, balanceStart - 8.5),
              updated_at: new Date().toISOString(),
            })
            .eq('user_id', userId);
          controller.enqueue(encoder.encode(encodeSse({ type: 'done' })));
          break;

        case 'iteration':
        case 'tool_call':
        default:
          break;
      }
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Orchestrator failed';
    controller.enqueue(encoder.encode(encodeSse({ type: 'error', message })));
  }
}
