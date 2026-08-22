import type { SupabaseClient } from '@supabase/supabase-js';
import type { AgentStep, PCBState, PCBStatus } from '@cirqix/types';
import { executeToolStub } from '@cirqix/agents';
import { encodeSse } from './sse';
import { uploadKicadArtifact } from './kicad-storage';
import { logger } from '@cirqix/logger';
import { finalizePipelineSuccess } from './credits';
import type { RunSink } from '@cirqix/agents';

const log = logger.child({ module: 'local-pipeline' });

/** Étape du pipeline dont le handler a renvoyé status:'error' — interrompt la chaîne. */
class PipelineStepError extends Error {}

interface PipelineOptions {
  sink: RunSink;
  supabase: SupabaseClient;
  userId: string;
  projectId: string;
  prompt: string;
  iterationStart: number;
  balanceStart: number;
}

async function streamText(
  sink: RunSink,
  text: string,
) {
  for (let i = 0; i < text.length; i += 6) {
    const slice = text.slice(i, i + 6);
    await sink.emit({ type: 'token', content: slice });
    await new Promise((r) => setTimeout(r, 10));
  }
}

export async function runLocalPipeline(opts: PipelineOptions): Promise<void> {
  const { sink, supabase, userId, projectId, prompt, iterationStart } = opts;

  let mergedState: Partial<PCBState> = {
    projectId,
    iteration: iterationStart + 1,
    status: 'INITIAL',
  };

  async function updateState(
    toolName: string,
    rawResult: Record<string, unknown>,
    fallbackStatus: PCBStatus,
    stepName: AgentStep,
  ) {
    await sink.emit({ type: 'step', step: stepName });

    // Le handler fait foi. Un outil en échec n'accorde AUCUN statut : on
    // interrompt le pipeline sans rien persister. Sans ce garde-fou, un DRC en
    // erreur (kicad-cli absent, KICAD_SERVICE_URL non configurée…) était écrit
    // DRC_CLEAN en base — or POST /api/jlcpcb/order autorise une commande dès
    // que projects.status vaut DRC_CLEAN, donc sur un board jamais validé.
    if (rawResult['status'] === 'error') {
      throw new PipelineStepError(
        String(rawResult['error'] ?? `${toolName} a échoué`),
      );
    }

    const schContent = rawResult['kicad_sch_content'];
    const pcbContent = rawResult['kicad_pcb_content'];

    let kicad_sch_url: string | undefined;
    let kicad_pcb_url: string | undefined;

    if (typeof schContent === 'string' && schContent.length > 0) {
      const up = await uploadKicadArtifact(supabase, userId, projectId, 'schematic.kicad_sch', schContent);
      if (up.signedUrl) kicad_sch_url = up.signedUrl;
    }
    if (typeof pcbContent === 'string' && pcbContent.length > 0) {
      const up = await uploadKicadArtifact(supabase, userId, projectId, 'pcb.kicad_pcb', pcbContent);
      if (up.signedUrl) kicad_pcb_url = up.signedUrl;
    }

    const rawWithoutContent = { ...rawResult };
    delete rawWithoutContent['kicad_sch_content'];
    delete rawWithoutContent['kicad_pcb_content'];

    // Ne jamais promouvoir au-delà de ce que le handler a réellement accordé :
    // un DRC ayant trouvé des violations renvoie ROUTING_DONE, pas DRC_CLEAN.
    const statusLabel: PCBStatus =
      (rawResult['pcb_status'] as PCBStatus | undefined) ?? fallbackStatus;

    mergedState = {
      ...mergedState,
      ...rawWithoutContent,
      projectId,
      status: statusLabel,
    } as Partial<PCBState>;

    if (kicad_sch_url) (mergedState as PCBState).kicad_sch_url = kicad_sch_url;
    if (kicad_pcb_url) (mergedState as PCBState).kicad_pcb_url = kicad_pcb_url;

    const finalized = mergedState as PCBState;
    if (statusLabel === 'DRC_CLEAN') {
      // PROVENANCE HONNÊTE : ce repli enchaîne les VRAIS handlers, mais saute
      // la résolution des footprints, la génération native du PCB et l'export.
      // Il n'est ni le pipeline complet ni le simulateur — d'où sa propre
      // valeur (migration 018). Le gate JLCPCB n'accepte que `orchestrator`,
      // donc ce board n'est pas commandable, et la RPC ne débite que pour
      // `orchestrator`, donc ce run ne facture rien.
      await finalizePipelineSuccess(supabase, userId, projectId, finalized, 'local_fallback');
    }
    await sink.emit({ type: 'pcb_state', state: finalized });
    await sink.emit({ type: 'status', status: statusLabel });

    if (statusLabel !== 'DRC_CLEAN') await supabase.from('projects').update({
      status: statusLabel,
      pcb_state: finalized,
      // Provenance : vrais handlers, mais footprint/gen_pcb/export sautés.
      // Ni orchestrateur complet, ni simulateur → board NON commandable.
      agent_mode: 'local_fallback',
      updated_at: new Date().toISOString(),
    }).eq('id', projectId);
  }

  try {
    await streamText(sink, "Running LOCAL pipeline (No Anthropic API required)...\n\n");
    
    await streamText(sink, "1. Generating Schema via Circuit-Synth...\n");
    const schema = await executeToolStub('call_agent_schema', { user_description: prompt, complexity: 'simple' }, projectId);
    await updateState('call_agent_schema', schema, 'SCHEMA_DONE', 'SCHEMA');

    await streamText(sink, "2. Running ERC...\n");
    const erc = await executeToolStub('call_agent_erc', { auto_fix: true }, projectId);
    await updateState('call_agent_erc', erc, 'ERC_CLEAN', 'ERC');

    await streamText(sink, "3. Placing components via Pcbnew...\n");
    // No board_width_mm/board_height_mm — call_agent_placement reads from schema cache.
    const placement = await executeToolStub('call_agent_placement', {}, projectId);
    await updateState('call_agent_placement', placement, 'PLACEMENT_DONE', 'PLACEMENT');

    await streamText(sink, "4. Routing tracks via Freerouting...\n");
    const routing = await executeToolStub('call_agent_routing', { placement_json: '{}', schema_json: '{}' }, projectId);
    await updateState('call_agent_routing', routing, 'ROUTING_DONE', 'ROUTING');

    await streamText(sink, "5. Running DRC...\n");
    const drc = await executeToolStub('call_agent_drc', { auto_fix: true }, projectId);
    if (drc['status'] === 'error') {
      await updateState('call_agent_drc', drc, 'DRC_CLEAN', 'DRC');
    }

    await updateState('call_agent_drc', drc, 'DRC_CLEAN', 'DRC');
    if (mergedState.status !== 'DRC_CLEAN') {
      throw new PipelineStepError('DRC completed with remaining violations');
    }
    await sink.emit({ type: 'step', step: null });
    await sink.emit({ type: 'done' });

  } catch (err) {
    const message = err instanceof Error ? err.message : 'Local pipeline failed';
    await sink.emit({ type: 'error', message });
  }
}
