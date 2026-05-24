import type { SupabaseClient } from '@supabase/supabase-js';
import type { PCBState, PCBStatus } from '@layrix/types';
import { runOrchestrator } from '@layrix/agents';
import { logger } from '@layrix/logger';
import { encodeSse } from './sse';
import { uploadKicadArtifact } from './kicad-storage';

const log = logger.child({ module: 'orchestrator-bridge' });

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
            const kicadServiceUrl = process.env.KICAD_SERVICE_URL;
            if (kicadServiceUrl) {
              try {
                const b64 = Buffer.from(raw.kicad_pcb_content).toString('base64');
                const boardWidth = (raw.board_width_mm as number) ?? (mergedState.board_width_mm as number) ?? 100;
                const boardHeight = (raw.board_height_mm as number) ?? (mergedState.board_height_mm as number) ?? 80;
                
                const res = await fetch(`${kicadServiceUrl}/place/auto`, {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({
                    kicad_pcb_b64: b64,
                    board_width_mm: boardWidth,
                    board_height_mm: boardHeight,
                  }),
                });
                
                if (res.ok) {
                  const json = await res.json() as any;
                  if (json.kicad_pcb_b64) {
                    raw.kicad_pcb_content = Buffer.from(json.kicad_pcb_b64, 'base64').toString('utf-8');
                    log.debug({ placedCount: json.placed_count }, 'auto-placement SUCCESS');
                  }
                } else {
                  log.error({ status: res.status, text: await res.text() }, 'auto-placement FAILED');
                }
              } catch (err) {
                log.error({ err }, 'auto-placement exception');
              }
            }

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
