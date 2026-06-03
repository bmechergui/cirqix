import { pcbStateCache } from '../shared';
import { runReasoner } from '../../engines/reasoning-service';

export async function handleReason(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const pcbContent = cached?.kicad_pcb_content;
  if (!pcbContent || pcbContent.length === 0) {
    return {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: 0,
      reasoning_steps: [],
      engine: 'fallback-skip',
      warning: 'No .kicad_pcb in cache — run call_agent_routing first.',
      note: 'Reasoner sauté — pas de PCB en cache.',
    };
  }

  const result = await runReasoner({ kicadPcbContent: pcbContent });
  const finalPcb = result.kicadPcbContent ?? pcbContent;
  if (cached) {
    pcbStateCache.set(projectId, { ...cached, kicad_pcb_content: finalPcb });
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
