import { describe, it, expect, vi } from 'vitest';
import { cloturerLeRunDuJobEchoue } from '../job-echoue.js';

/**
 * Un job échoué par BullMQ hors de `runJob` (stalled) doit clôturer son run —
 * mesure du 2026-09-13, run 9de5a20d resté `running` pour toujours.
 */
function deps(statut: string | null) {
  return {
    lireStatut: vi.fn().mockResolvedValue(statut),
    finish: vi.fn().mockResolvedValue(undefined),
  };
}
const job = { id: 'project-x', data: { runId: '9de5a20d-c8d6-4a6a-a2b3-e645734e9c70' } };

describe('cloturerLeRunDuJobEchoue', () => {
  it('un run encore running est marqué failed avec la cause', async () => {
    const d = deps('running');
    expect(await cloturerLeRunDuJobEchoue(job, new Error('job stalled more than allowable limit'), d)).toBe(true);
    expect(d.finish).toHaveBeenCalledWith(job.data.runId, 'failed', 'job échoué hors pipeline : job stalled more than allowable limit');
  });
  it('un run queued aussi', async () => {
    const d = deps('queued');
    expect(await cloturerLeRunDuJobEchoue(job, 'données illisibles', d)).toBe(true);
    expect(d.finish).toHaveBeenCalledOnce();
  });
  it('un run déjà clos par runJob n est pas réécrit', async () => {
    for (const s of ['succeeded', 'failed', 'cancelled']) {
      const d = deps(s);
      expect(await cloturerLeRunDuJobEchoue(job, new Error('x'), d)).toBe(false);
      expect(d.finish).not.toHaveBeenCalled();
    }
  });
  it('un job sans runId ou un run introuvable ne fait rien', async () => {
    const d = deps(null);
    expect(await cloturerLeRunDuJobEchoue(undefined, new Error('x'), d)).toBe(false);
    expect(await cloturerLeRunDuJobEchoue({ id: 'j', data: {} }, new Error('x'), d)).toBe(false);
    expect(await cloturerLeRunDuJobEchoue(job, new Error('x'), d)).toBe(false);
    expect(d.finish).not.toHaveBeenCalled();
  });
});
