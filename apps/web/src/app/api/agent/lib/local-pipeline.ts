import type { SupabaseClient } from '@supabase/supabase-js';
import type { AgentStep, PCBState, PCBStatus } from '@cirqix/types';
import { executeToolStub } from '@cirqix/agents';
import { encodeSse } from './sse';
import { uploadKicadArtifact } from './kicad-storage';
import { logger } from '@cirqix/logger';

const log = logger.child({ module: 'local-pipeline' });

interface PipelineOptions {
  controller: ReadableStreamDefaultController<Uint8Array>;
  encoder: TextEncoder;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
  balanceStart: number;
}

async function streamText(
  controller: ReadableStreamDefaultController<Uint8Array>,
  encoder: TextEncoder,
  text: string,
) {
  for (let i = 0; i < text.length; i += 6) {
    const slice = text.slice(i, i + 6);
    controller.enqueue(encoder.encode(encodeSse({ type: 'token', content: slice })));
    await new Promise((r) => setTimeout(r, 10));
  }
}

export async function runLocalPipeline(opts: PipelineOptions): Promise<void> {
  const { controller, encoder, supabase, userId, projectId, prompt, iterationStart } = opts;

  let mergedState: Partial<PCBState> = {
    projectId,
    iteration: iterationStart + 1,
    status: 'INITIAL',
  };

  async function updateState(toolName: string, rawResult: any, statusLabel: PCBStatus, stepName: AgentStep) {
    controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: stepName })));
    
    let kicad_sch_url: string | undefined;
    let kicad_pcb_url: string | undefined;
    
    if (typeof rawResult.kicad_sch_content === 'string' && rawResult.kicad_sch_content.length > 0) {
      const up = await uploadKicadArtifact(supabase, userId, projectId, 'schematic.kicad_sch', rawResult.kicad_sch_content);
      if (up.signedUrl) kicad_sch_url = up.signedUrl;
    }
    if (typeof rawResult.kicad_pcb_content === 'string' && rawResult.kicad_pcb_content.length > 0) {
      const up = await uploadKicadArtifact(supabase, userId, projectId, 'pcb.kicad_pcb', rawResult.kicad_pcb_content);
      if (up.signedUrl) kicad_pcb_url = up.signedUrl;
    }

    const rawWithoutContent = { ...rawResult };
    delete rawWithoutContent.kicad_sch_content;
    delete rawWithoutContent.kicad_pcb_content;

    mergedState = {
      ...mergedState,
      ...rawWithoutContent,
      projectId,
      status: statusLabel,
    } as Partial<PCBState>;

    if (kicad_sch_url) (mergedState as PCBState).kicad_sch_url = kicad_sch_url;
    if (kicad_pcb_url) (mergedState as PCBState).kicad_pcb_url = kicad_pcb_url;

    const finalized = mergedState as PCBState;
    controller.enqueue(encoder.encode(encodeSse({ type: 'pcb_state', state: finalized })));
    controller.enqueue(encoder.encode(encodeSse({ type: 'status', status: statusLabel })));

    await supabase.from('projects').update({
      status: statusLabel,
      pcb_state: finalized,
      iteration_count: finalized.iteration,
      updated_at: new Date().toISOString(),
    }).eq('id', projectId);
  }

  try {
    await streamText(controller, encoder, "Running LOCAL pipeline (No Anthropic API required)...\n\n");
    
    await streamText(controller, encoder, "1. Generating Schema via Circuit-Synth...\n");
    const schema = await executeToolStub('call_agent_schema', { user_description: prompt, complexity: 'simple' }, projectId);
    await updateState('call_agent_schema', schema, 'SCHEMA_DONE', 'SCHEMA');

    await streamText(controller, encoder, "2. Running ERC...\n");
    const erc = await executeToolStub('call_agent_erc', { auto_fix: true }, projectId);
    await updateState('call_agent_erc', erc, 'ERC_CLEAN', 'ERC');

    await streamText(controller, encoder, "3. Placing components via Pcbnew...\n");
    // No board_width_mm/board_height_mm — call_agent_placement reads from schema cache.
    const placement = await executeToolStub('call_agent_placement', {}, projectId);
    await updateState('call_agent_placement', placement, 'PLACEMENT_DONE', 'PLACEMENT');

    await streamText(controller, encoder, "4. Routing tracks via Freerouting...\n");
    const routing = await executeToolStub('call_agent_routing', { placement_json: '{}', schema_json: '{}' }, projectId);
    await updateState('call_agent_routing', routing, 'ROUTING_DONE', 'ROUTING');

    await streamText(controller, encoder, "5. Running DRC...\n");
    const drc = await executeToolStub('call_agent_drc', { auto_fix: true }, projectId);
    await updateState('call_agent_drc', drc, 'DRC_CLEAN', 'DRC');

    controller.enqueue(encoder.encode(encodeSse({ type: 'step', step: null })));
    controller.enqueue(encoder.encode(encodeSse({ type: 'done' })));

  } catch (err) {
    const message = err instanceof Error ? err.message : 'Local pipeline failed';
    controller.enqueue(encoder.encode(encodeSse({ type: 'error', message })));
  }
}
