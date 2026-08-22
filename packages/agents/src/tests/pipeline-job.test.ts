import { describe, it, expect } from 'vitest';
import {
  PIPELINE_QUEUE_NAME,
  PipelineJobPayload,
  WORKER_OPTIONS,
  JOB_OPTIONS,
  jobIdForProject,
} from '../pipeline/job';

/**
 * Contrat du job de pipeline.
 *
 * Deux invariants, chacun payé par un mode d'échec précis.
 *
 * 1. LA PROVENANCE NE VOYAGE PAS DANS LE PAYLOAD. `agent_mode` gouverne le gate
 *    de commande JLCPCB — une commande réelle et payante. S'il transitait par le
 *    job, enfiler un job reviendrait à décerner la commandabilité. Il est posé
 *    par la route dans `pcb_runs` et relu depuis la base par le worker.
 *
 * 2. UN JOB « STALLED » NE DOIT JAMAIS ÊTRE REJOUÉ. Par défaut BullMQ redonne un
 *    job dont le verrou a expiré — potentiellement EN PARALLÈLE du premier,
 *    toujours vivant. Sur un routage de 20 minutes, le verrou par défaut (30 s)
 *    expire largement avant la fin : ce serait deux routages concurrents sur la
 *    même carte, chacun écrasant l'artefact de l'autre.
 */

describe('payload du job', () => {
  it('accepte un job bien formé', () => {
    const parsed = PipelineJobPayload.safeParse({
      runId: '3f0e57c0-0000-4000-8000-000000000000',
      projectId: '9739d1f0-0000-4000-8000-000000000000',
      userId: 'a1899340-0000-4000-8000-000000000000',
      prompt: 'un blinker NE555',
      iterationStart: 0,
    });
    expect(parsed.success).toBe(true);
  });

  it('REFUSE une provenance dans le payload', () => {
    const parsed = PipelineJobPayload.safeParse({
      runId: '3f0e57c0-0000-4000-8000-000000000000',
      projectId: '9739d1f0-0000-4000-8000-000000000000',
      userId: 'a1899340-0000-4000-8000-000000000000',
      prompt: 'un blinker',
      iterationStart: 0,
      agentMode: 'orchestrator',
    });
    // Strict : un champ inconnu est rejeté. Enfiler un job ne peut pas décerner
    // la commandabilité JLCPCB.
    expect(parsed.success).toBe(false);
  });

  it('refuse un prompt vide et une itération négative', () => {
    const base = {
      runId: '3f0e57c0-0000-4000-8000-000000000000',
      projectId: '9739d1f0-0000-4000-8000-000000000000',
      userId: 'a1899340-0000-4000-8000-000000000000',
    };
    expect(PipelineJobPayload.safeParse({ ...base, prompt: '', iterationStart: 0 }).success)
      .toBe(false);
    expect(PipelineJobPayload.safeParse({ ...base, prompt: 'x', iterationStart: -1 }).success)
      .toBe(false);
  });

  it('refuse un identifiant qui n est pas un uuid', () => {
    expect(
      PipelineJobPayload.safeParse({
        runId: 'pas-un-uuid',
        projectId: '9739d1f0-0000-4000-8000-000000000000',
        userId: 'a1899340-0000-4000-8000-000000000000',
        prompt: 'x',
        iterationStart: 0,
      }).success,
    ).toBe(false);
  });
});

describe('réglages BullMQ — les défauts sont dangereux ici', () => {
  it('ne rejoue JAMAIS un job stalled', () => {
    // Défaut BullMQ : 1. Un routage de 20 min verrait son verrou expirer et le
    // job repartir en parallèle du premier.
    expect(WORKER_OPTIONS.maxStalledCount).toBe(0);
  });

  it('ne réessaie pas automatiquement', () => {
    // Un pipeline qui a échoué a consommé des crédits et produit un artefact
    // partiel. Le rejouer sans décision humaine doublerait la dépense.
    expect(JOB_OPTIONS.attempts).toBe(1);
  });

  it('tient un verrou plus long que le défaut de 30 s', () => {
    expect(WORKER_OPTIONS.lockDuration).toBeGreaterThanOrEqual(60_000);
  });

  it('traite un seul job à la fois — le service KiCad est le goulot', () => {
    expect(WORKER_OPTIONS.concurrency).toBe(1);
  });
});

describe('déduplication par projet', () => {
  it('dérive l identifiant de job du projet', () => {
    expect(jobIdForProject('p1')).toBe(jobIdForProject('p1'));
    expect(jobIdForProject('p1')).not.toBe(jobIdForProject('p2'));
  });

  it('produit un identifiant que BullMQ accepte', () => {
    // BullMQ REFUSE un `jobId` custom contenant `:` — `Job.validateOptions`
    // lève `Custom Id cannot contain :`, car il compose ses propres clés Redis
    // avec ce séparateur. L'ancien `project:<uuid>` faisait donc échouer
    // CHAQUE enfilage, et les tests ne le voyaient pas : ils comparaient
    // `jobIdForProject` à lui-même sans jamais confronter le résultat à la
    // contrainte de la librairie. Trouvé en enfilant un vrai job.
    expect(jobIdForProject('11111111-1111-4111-8111-111111111111')).not.toContain(':');
  });

  it('nomme la file de façon stable', () => {
    expect(PIPELINE_QUEUE_NAME).toBe('pcb-pipeline');
  });
});
