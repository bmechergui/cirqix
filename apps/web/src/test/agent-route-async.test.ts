import { describe, it, expect, vi, beforeEach } from 'vitest';

/**
 * Branche asynchrone de `POST /api/agent`.
 *
 * Elle touche deux choses coûteuses, d'où ces gardes.
 *
 * 1. LA PROVENANCE. `agent_mode` est écrit dans `pcb_runs` par la ROUTE, jamais
 *    transporté dans le payload du job. Si un job pouvait la porter, enfiler un
 *    job reviendrait à décerner la commandabilité JLCPCB — une commande réelle
 *    et payante. `PipelineJobPayload` est en mode strict pour rendre la
 *    tentative bruyante ; ce test verrouille l'intention côté appelant.
 *
 * 2. LA RÉSERVATION DE CRÉDITS. Elle est posée AVANT l'enfilage. Si celui-ci
 *    échoue, le run n'a jamais démarré : rendre la retenue tout de suite évite
 *    de geler le solde de l'utilisateur jusqu'à l'expiration du TTL, pour un
 *    travail qui n'aura pas lieu.
 */

import { PipelineJobPayload } from '@cirqix/agents';
import { asyncPipelineEnabled } from '@/app/api/agent/lib/async-mode';

const VALID = {
  runId: '11111111-1111-4111-8111-111111111111',
  projectId: '22222222-2222-4222-8222-222222222222',
  userId: '33333333-3333-4333-8333-333333333333',
  prompt: 'un blinker NE555',
  iterationStart: 0,
};

describe('la provenance ne peut pas voyager par la file', () => {
  it('accepte le payload que la route construit', () => {
    expect(PipelineJobPayload.safeParse(VALID).success).toBe(true);
  });

  it('rejette toute tentative d y glisser une provenance', () => {
    for (const smuggled of [
      { agentMode: 'orchestrator' },
      { agent_mode: 'orchestrator' },
      { status: 'DRC_CLEAN' },
    ]) {
      const parsed = PipelineJobPayload.safeParse({ ...VALID, ...smuggled });
      expect(parsed.success, `${JSON.stringify(smuggled)} aurait dû être refusé`).toBe(false);
    }
  });
});

describe('le drapeau protège contre une bascule incomplète', () => {
  beforeEach(() => vi.unstubAllEnvs());

  it('laisse le chemin SSE actif tant que rien n est demandé', () => {
    expect(asyncPipelineEnabled({ REDIS_URL: 'redis://redis:6379' })).toBe(false);
  });

  it('refuse d accepter des runs que personne ne consommerait', () => {
    // Sans Redis, un `202` serait un mensonge : la demande serait acceptée puis
    // jamais traitée, et la réservation de crédits gelée jusqu'à son TTL.
    expect(
      asyncPipelineEnabled({ CIRQIX_ASYNC_PIPELINE: '1' }, { requireRedis: true }),
    ).toBe(false);
  });

  it('n active la bascule que si file ET drapeau sont là', () => {
    expect(
      asyncPipelineEnabled(
        { CIRQIX_ASYNC_PIPELINE: '1', REDIS_URL: 'redis://redis:6379' },
        { requireRedis: true },
      ),
    ).toBe(true);
  });
});
