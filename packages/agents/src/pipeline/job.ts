/**
 * Contrat du job de pipeline PCB.
 *
 * Le pipeline quitte l'invocation web parce qu'il ne peut pas y tenir : un
 * routage complexe dure 15-20 min et davantage, l'invocation est plafonnée à
 * 300 s. Ce module définit ce qui traverse la file — et surtout ce qui NE la
 * traverse PAS.
 */

import { z } from 'zod';

/** Nom de file. Stable : le changer orphelinerait les jobs en vol. */
export const PIPELINE_QUEUE_NAME = 'pcb-pipeline';

/**
 * Ce que le worker reçoit.
 *
 * ⚠️ `strict()` n'est pas une coquetterie. `agent_mode` — la PROVENANCE — est
 * délibérément ABSENTE de ce payload : elle gouverne le gate de
 * `POST /api/jlcpcb/order`, c'est-à-dire une commande réelle et payante. Si elle
 * voyageait ici, **enfiler un job reviendrait à décerner la commandabilité**.
 *
 * Elle est posée par la ROUTE dans `pcb_runs.agent_mode` à la création du run,
 * et relue depuis la base par le worker. La RPC de finalisation compare ensuite
 * la provenance qu'elle reçoit à celle enregistrée : un worker buggé ne peut
 * plus promouvoir un `local_fallback` en `orchestrator`.
 *
 * Le mode strict fait échouer bruyamment toute tentative d'en ajouter une, au
 * lieu de l'ignorer en silence.
 */
export const PipelineJobPayload = z
  .object({
    runId: z.string().uuid(),
    projectId: z.string().uuid(),
    userId: z.string().uuid(),
    prompt: z.string().min(1),
    iterationStart: z.number().int().min(0),
  })
  .strict();

export type PipelineJobPayload = z.infer<typeof PipelineJobPayload>;

/**
 * Un seul job vivant par projet.
 *
 * BullMQ déduplique nativement sur `jobId` : un job dont l'id existe déjà n'est
 * pas ajouté. C'est la première des deux barrières — la seconde est l'index
 * unique partiel `pcb_runs_one_alive_per_project` (migration 019), qui tient
 * encore si Redis est vidé.
 *
 * Deux runs concurrents se disputeraient `iteration_count` et l'artefact du
 * board, chacun écrasant celui de l'autre.
 */
export function jobIdForProject(projectId: string): string {
  return `project:${projectId}`;
}

/**
 * Options de job.
 *
 * `attempts: 1` — AUCUN réessai automatique. Un pipeline échoué a déjà consommé
 * du Sonnet, du Haiku et du CPU KiCad, et laissé un artefact partiel. Le rejouer
 * sans décision humaine doublerait la dépense sans garantie de succès. La
 * relance est une action explicite de l'utilisateur.
 */
export const JOB_OPTIONS = {
  attempts: 1,
  removeOnComplete: { count: 100 },
  removeOnFail: { count: 500 },
} as const;

/**
 * Options du worker — les défauts de BullMQ sont dangereux pour cette charge.
 *
 * `maxStalledCount: 0` — LE réglage critique. Par défaut (1), BullMQ redonne un
 * job dont le verrou a expiré, potentiellement EN PARALLÈLE du premier toujours
 * vivant. Sur un routage de 20 minutes, le verrou par défaut (30 s) expire
 * largement avant la fin : ce seraient deux routages concurrents sur la même
 * carte. À 0, un job « stalled » est marqué échoué, jamais rejoué.
 *
 * `lockDuration: 60_000` — le renouvellement du verrou est automatique tant que
 * le worker vit ; une fenêtre plus large absorbe une pause du processus (GC,
 * contention CPU pendant un routage) sans déclencher le mécanisme ci-dessus.
 *
 * `concurrency: 1` — le goulot est le service KiCad (routage CPU-bound sur la
 * même droplet), pas le worker, qui n'attend que des réponses HTTP. Traiter deux
 * jobs de front ralentirait les deux. À mesurer avant d'augmenter.
 */
export const WORKER_OPTIONS = {
  concurrency: 1,
  lockDuration: 60_000,
  maxStalledCount: 0,
} as const;
