// Barrel public de l'agent toolset. Surface inchangée : PCB_TOOLS, ACTIVE_PCB_TOOLS,
// executeToolStub — importés via './tools' par index.ts (package), orchestrator.ts et
// les tests. Chaque agent vit dans son propre module sous ./handlers/.
export { PCB_TOOLS, ACTIVE_PCB_TOOLS } from './definitions';

import { handleSpec, handleAskUser } from './handlers/misc';
import { handleSchema } from './handlers/schema';
import { handleErc } from './handlers/erc';
import { handleFootprint } from './handlers/footprint';
import { handleGenPcb } from './handlers/gen-pcb';
import { handlePlacement } from './handlers/placement';
import { handleRouting } from './handlers/routing';
import { handleReason } from './handlers/reason';
import { handleDrc } from './handlers/drc';
import { handleExport } from './handlers/export';
import { handleSimulation } from './handlers/simulation';

export async function executeToolStub(
  toolName: string,
  input: Record<string, unknown>,
  projectId = 'default'
): Promise<Record<string, unknown>> {
  switch (toolName) {
    case 'call_agent_spec':
      return handleSpec();
    case 'call_agent_schema':
      return handleSchema(input, projectId);
    case 'call_agent_erc':
      return handleErc(input, projectId);
    case 'call_agent_footprint':
      return handleFootprint(input, projectId);
    case 'call_agent_gen_pcb':
      return handleGenPcb(projectId);
    case 'call_agent_placement':
      return handlePlacement(input, projectId);
    case 'call_agent_routing':
      return handleRouting(projectId);
    case 'call_agent_reason':
      return handleReason(projectId);
    case 'call_agent_drc':
      return handleDrc(input, projectId);
    case 'call_agent_export':
      return handleExport(projectId);
    case 'call_agent_simulation':
      return handleSimulation(input, projectId);
    case 'ask_user':
      return handleAskUser(input);
    default:
      return { status: 'error', message: `Outil inconnu: ${toolName}` };
  }
}
