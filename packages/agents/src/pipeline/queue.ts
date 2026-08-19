/**
 * Producteur et consommateur de la file de pipelines PCB.
 *
 * Isole BullMQ derrière deux fabriques, pour deux raisons :
 *   - les réglages critiques (`WORKER_OPTIONS`, `JOB_OPTIONS`) sont appliqués
 *     ici et nulle part ailleurs — un appelant ne peut pas les oublier ;
 *   - `bullmq` et `ioredis` ne sont importés que par ce fichier, donc la route
 *     web n'embarque pas le worker et réciproquement.
 */

import { Queue, Worker, type Job } from 'bullmq';
import IORedis from 'ioredis';
import {
  PIPELINE_QUEUE_NAME,
  PipelineJobPayload,
  JOB_OPTIONS,
  WORKER_OPTIONS,
  jobIdForProject,
} from './job';

/**
 * Connexion Redis.
 *
 * `maxRetriesPerRequest: null` est EXIGÉ par BullMQ : ses commandes bloquantes
 * (BZPOPMIN) restent en attente longtemps, et le défaut d'ioredis les ferait
 * échouer au bout de quelques essais.
 */
function connection(redisUrl: string): IORedis {
  return new IORedis(redisUrl, { maxRetriesPerRequest: null });
}

export function createPipelineQueue(redisUrl: string): Queue<PipelineJobPayload> {
  return new Queue<PipelineJobPayload>(PIPELINE_QUEUE_NAME, {
    connection: connection(redisUrl),
    defaultJobOptions: JOB_OPTIONS,
  });
}

/**
 * Enfile un run. Valide le payload AVANT l'envoi : un job malformé échouerait
 * dans le worker, loin de l'appelant, et après avoir déjà consommé une
 * réservation de crédits.
 *
 * `jobId` dérive du projet : BullMQ déduplique donc nativement. Un second
 * enfilage sur le même projet est ignoré plutôt que de doubler le travail.
 */
export async function enqueuePipelineRun(
  queue: Queue<PipelineJobPayload>,
  payload: PipelineJobPayload,
): Promise<void> {
  const parsed = PipelineJobPayload.parse(payload);
  await queue.add(PIPELINE_QUEUE_NAME, parsed, {
    jobId: jobIdForProject(parsed.projectId),
  });
}

/** Ce que le worker exécute pour un job. */
export type PipelineRunner = (payload: PipelineJobPayload) => Promise<void>;

/**
 * Démarre le consommateur.
 *
 * Le payload est RE-VALIDÉ à la réception : un job peut avoir été écrit par une
 * version antérieure du producteur, ou avoir dormi en file pendant un
 * déploiement.
 */
export function createPipelineWorker(
  redisUrl: string,
  runner: PipelineRunner,
): Worker<PipelineJobPayload> {
  return new Worker<PipelineJobPayload>(
    PIPELINE_QUEUE_NAME,
    async (job: Job<PipelineJobPayload>) => {
      await runner(PipelineJobPayload.parse(job.data));
    },
    { connection: connection(redisUrl), ...WORKER_OPTIONS },
  );
}
