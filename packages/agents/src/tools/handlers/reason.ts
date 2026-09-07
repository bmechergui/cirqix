import { pcbStateCache } from '../shared';
import { runReasoner } from '../../engines/reasoning-service';

export async function handleReason(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const pcbContent = cached?.kicad_pcb_content;
  if (!pcbContent || pcbContent.length === 0) {
    // ⚠️ ECHEC FERME. Ce handler etait le SEUL des huit a rendre encore
    // `status:'success'` et a promouvoir `pcb_status:'ROUTING_DONE'` sur un
    // board qui n existe pas — les sept autres ont recu ce correctif le
    // 2026-07-27.
    //
    // L enjeu : `orchestrator-bridge` persiste `pcb_status` dans
    // `projects.status`. Un projet pouvait donc porter ROUTING_DONE sans
    // qu aucun board n ait ete produit.
    //
    // La branche est aujourd hui INATTEIGNABLE : `shouldRescueRouting` exige
    // un `routed_percent` numerique, donc un routage reussi, qui a lui-meme
    // ecrit le cache. On la ferme quand meme — elle est a un changement de
    // declencheur pres de s ouvrir, et « inatteignable aujourd hui » n est pas
    // une garantie, c est une coincidence.
    //
    // La fusion (`mergeRescueIntoRouting`) n en souffre pas : sans
    // `kicad_pcb_content` elle conserve deja le routage d origine, et le
    // `status` du routage l emporte.
    return {
      status: 'error',
      error: 'No .kicad_pcb in cache — run call_agent_routing first.',
      routed_percent: 0,
      reasoning_steps: [],
      engine: 'fallback-skip',
      note: 'Reasoner impossible — aucun PCB en cache, aucun statut promu.',
    };
  }

  const result = await runReasoner({ kicadPcbContent: pcbContent });
  const finalPcb = result.kicadPcbContent ?? pcbContent;
  // Reasoner may move footprints / tracks → prior DRC validation is stale.
  if (cached) {
    const { drc_clean: _stale, ...rest } = cached;
    pcbStateCache.set(projectId, { ...rest, kicad_pcb_content: finalPcb });
  }
  const brain = result.usedLlm ? 'LLM Claude' : 'heuristique';
  return {
    status: 'success',
    pcb_status: 'ROUTING_DONE',
    routed_percent: result.routedPercent,
    reasoning_steps: result.steps, // visible UI/SSE
    kicad_pcb_content: finalPcb,
    engine: result.usedLlm ? 'reasoner-llm' : 'reasoner-heuristic',
    warning: result.warning,
    note:
      `Reasoner IA (${brain}) — routage relevé à ${result.routedPercent}% ` +
      `en ${result.steps.length} action(s).`,
  };
}
