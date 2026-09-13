/**
 * Un job que BullMQ fait échouer SANS passer par `runJob` — « job stalled more
 * than allowable limit », données illisibles — laisse son run tel qu'il
 * était : `queued` ou `running`, pour toujours. Le navigateur affiche alors un
 * run qui tourne, et le crédit retenu attend l'expiration.
 *
 * ⚠️ Mesure du 2026-09-13, run 9de5a20d : le worker hôte est mort en plein
 * placement (garde-mémoire de l'outil), un nouveau worker a reçu le job en
 * `stalled`, BullMQ l'a déclaré échoué… et `pcb_runs.status` est resté
 * `running`. Le gestionnaire `failed` ne faisait que journaliser.
 *
 * On ne clôture QUE ce qui est encore ouvert : un run déjà `succeeded`,
 * `failed` ou `cancelled` par `runJob` n'est pas réécrit.
 */
export interface JobEchoue {
  id?: string;
  data?: { runId?: unknown };
}

export interface ClotureDeps {
  lireStatut: (runId: string) => Promise<string | null>;
  finish: (runId: string, status: 'failed', message?: string) => Promise<void>;
}

const OUVERTS = new Set(['queued', 'running']);

export async function cloturerLeRunDuJobEchoue(
  job: JobEchoue | undefined,
  err: unknown,
  deps: ClotureDeps,
): Promise<boolean> {
  const runId = job?.data?.runId;
  if (typeof runId !== 'string' || !runId) return false;
  const statut = await deps.lireStatut(runId);
  if (!statut || !OUVERTS.has(statut)) return false;
  const message = err instanceof Error ? err.message : String(err ?? 'job échoué');
  await deps.finish(runId, 'failed', `job échoué hors pipeline : ${message}`);
  return true;
}
