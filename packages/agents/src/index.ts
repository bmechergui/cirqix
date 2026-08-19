// Agents package — boucle agentique Claude SDK
export * from './types';
export * from './orchestrator';
export { PCB_TOOLS, executeToolStub } from './tools';
// Contexte de run : le plan gouverne des droits réels (plafond de couches).
// Semé par la route agent AVANT le premier appel d'outil, libéré à la fin.
export { setProjectPlan, getProjectPlan, clearProjectPlan } from './tools/shared';
export { runPCBEngine, selectEngine, runCircuitSynthEngine, isCircuitSynthAvailable } from './engines/engine-router';
export type { SchemaComponent, SchemaPin, SchemaNet, SchemaJson } from '@cirqix/types';
export type { PCBEngine, PCBEngineResult } from './engines/engine-router';
// Budget d'invocation : `maxDuration` de la route agent et les plafonds des
// clients HTTP décrivent la même limite d'horloge murale. Exporté ici pour que
// la garde de synchronisation (apps/web) puisse la lire sans chemin relatif.
export {
  INVOCATION_BUDGET_MS,
  RESPONSE_MARGIN_MS,
  STEP_CAP_MS,
  STEP_MINIMUM_MS,
  PipelineBudgetExceededError,
  createPipelineDeadline,
} from './pipeline-budget';
export type { BudgetedStep, PipelineDeadline } from './pipeline-budget';
