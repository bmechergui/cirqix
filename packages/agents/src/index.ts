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
// Contrat de sortie du pipeline : ce qui le décroche du flux SSE de Next, donc
// de l'invocation plafonnée. Voir `pipeline/run-sink.ts`.
export type { RunEvent, RunSink } from './pipeline/run-sink';
// Transport durable du journal de run (worker) et contrat de file.
export { PgSink, TOKEN_FLUSH_MS } from './pipeline/pg-sink';
export type { RunEventRow, RunEventWriter } from './pipeline/pg-sink';
export {
  PIPELINE_QUEUE_NAME,
  PipelineJobPayload,
  JOB_OPTIONS,
  WORKER_OPTIONS,
  jobIdForProject,
} from './pipeline/job';
// Pipeline orchestrateur, decouple de Supabase et du flux SSE : executable
// aussi bien dans la route web que dans le worker persistant.
export { runOrchestratorPipeline } from './pipeline/run-orchestrator';
export type { RunPipelineOptions } from './pipeline/run-orchestrator';
export type { KicadArtifactName, PipelineStore, StoredArtifact } from './pipeline/store';
// File BullMQ.
//
// Exporte depuis l'entree principale plutot que par un sous-chemin
// (`@cirqix/agents/pipeline-queue`) : le resolveur de vitest n'honore pas les
// sous-chemins d'`exports` pour un paquet lie en workspace, et les tests de la
// route echouaient a la resolution. Le cout est que `bullmq`/`ioredis` sont
// charges par tout consommateur du paquet -- acceptable, tous etant cote
// serveur, et aucune connexion n'etant ouverte a l'import (les fabriques seules
// se connectent).
export {
  createPipelineQueue,
  enqueuePipelineRun,
  createPipelineWorker,
} from './pipeline/queue';
export type { PipelineRunner } from './pipeline/queue';
