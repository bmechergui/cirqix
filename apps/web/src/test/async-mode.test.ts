import { describe, it, expect } from 'vitest';
import { asyncPipelineEnabled } from '@/app/api/agent/lib/async-mode';

/**
 * Drapeau de bascule vers le pipeline asynchrone.
 *
 * La route et le client doivent basculer ENSEMBLE : passer la route en `202`
 * pendant que le client attend un flux SSE casserait l'application. Le drapeau
 * permet de livrer les deux chemins, de valider l'asynchrone sur un
 * environnement réel, et de ne changer le défaut qu'ensuite.
 *
 * Il échoue FERMÉ : toute valeur non explicitement affirmative laisse le
 * comportement actuel. Un drapeau mal orthographié doit être sans effet, pas
 * activer silencieusement un chemin non validé.
 */
describe('drapeau du pipeline asynchrone', () => {
  it('est inactif par défaut', () => {
    expect(asyncPipelineEnabled({})).toBe(false);
  });

  it('s active sur une valeur explicitement affirmative', () => {
    expect(asyncPipelineEnabled({ CIRQIX_ASYNC_PIPELINE: '1' })).toBe(true);
    expect(asyncPipelineEnabled({ CIRQIX_ASYNC_PIPELINE: 'true' })).toBe(true);
  });

  it('reste inactif sur toute autre valeur', () => {
    for (const value of ['0', 'false', '', 'oui', 'yes', 'TRUE ', 'on']) {
      expect(asyncPipelineEnabled({ CIRQIX_ASYNC_PIPELINE: value })).toBe(false);
    }
  });

  it('exige une URL Redis — sans file, rien ne consommerait le job', () => {
    // Activer le drapeau sans Redis produirait des runs `queued` éternels :
    // l'utilisateur verrait sa demande acceptée puis jamais traitée.
    expect(
      asyncPipelineEnabled({ CIRQIX_ASYNC_PIPELINE: '1' }, { requireRedis: true }),
    ).toBe(false);
    expect(
      asyncPipelineEnabled(
        { CIRQIX_ASYNC_PIPELINE: '1', REDIS_URL: 'redis://redis:6379' },
        { requireRedis: true },
      ),
    ).toBe(true);
  });
});
