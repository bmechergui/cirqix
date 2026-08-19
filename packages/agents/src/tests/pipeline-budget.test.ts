import { describe, it, expect } from 'vitest';

/**
 * Budget d'invocation du pipeline.
 *
 * `apps/web/src/app/api/agent/route.ts` exporte `maxDuration = 300`. Ce n'est
 * pas un réglage applicatif : c'est un plafond d'HORLOGE MURALE imposé par la
 * plateforme à l'invocation entière. `async`/`await` n'y change rien — la
 * fonction reste ouverte tant qu'elle tient le flux SSE, qu'elle calcule ou
 * qu'elle attende un `fetch`.
 *
 * Symptôme mesuré avant ce module : `ROUTING_TIMEOUT_MS = 330_000` dépassait
 * `maxDuration` de 30 s. Le garde-fou `AbortSignal.timeout(330_000)` ne pouvait
 * donc JAMAIS se déclencher en production — la plateforme tuait la fonction
 * avant. Un filet inatteignable, et un run perdu sans message d'erreur.
 *
 * Ce module ne « re-règle » pas les plafonds : placement (180 s) + routage
 * (330 s) valent 510 s à eux seuls, aucun jeu de constantes fixes ne tient dans
 * 300 s. Il impose une ÉCHÉANCE vérifiée avant chaque étape longue, pour que le
 * pipeline échoue honnêtement au lieu d'être tué en vol.
 */

import {
  INVOCATION_BUDGET_MS,
  RESPONSE_MARGIN_MS,
  STEP_CAP_MS,
  STEP_MINIMUM_MS,
  PipelineBudgetExceededError,
  createPipelineDeadline,
} from '../pipeline-budget';

describe('constantes de budget', () => {
  it('aucun plafond d étape ne dépasse le budget d invocation', () => {
    // Régression directe du bug ROUTING_TIMEOUT_MS = 330_000 > maxDuration.
    for (const [step, cap] of Object.entries(STEP_CAP_MS)) {
      expect(cap, `${step} dépasse le budget d'invocation`).toBeLessThanOrEqual(
        INVOCATION_BUDGET_MS - RESPONSE_MARGIN_MS,
      );
    }
  });

  it('garde une marge pour signaler l erreur avant que la plateforme ne coupe', () => {
    expect(RESPONSE_MARGIN_MS).toBeGreaterThan(0);
    expect(RESPONSE_MARGIN_MS).toBeLessThan(INVOCATION_BUDGET_MS);
  });

  it('chaque étape a un minimum strictement inférieur à son plafond', () => {
    for (const step of Object.keys(STEP_CAP_MS) as (keyof typeof STEP_CAP_MS)[]) {
      expect(STEP_MINIMUM_MS[step]).toBeGreaterThan(0);
      expect(STEP_MINIMUM_MS[step]).toBeLessThan(STEP_CAP_MS[step]);
    }
  });
});

describe('createPipelineDeadline', () => {
  it('rabote le plafond d une étape sur le temps réellement restant', () => {
    const deadline = createPipelineDeadline(0);
    // 180 s consommées : il reste 120 s, dont 105 s utilisables une fois la
    // marge de réponse réservée — bien au-dessus du minimum du routage (45 s),
    // donc l'étape part, mais avec 105 s au lieu de son plafond nominal.
    const granted = deadline.budgetFor('routing', 180_000);
    expect(granted).toBe(INVOCATION_BUDGET_MS - 180_000 - RESPONSE_MARGIN_MS);
    expect(granted).toBeLessThan(STEP_CAP_MS.routing);
    expect(granted).toBeGreaterThan(STEP_MINIMUM_MS.routing);
  });

  it('refuse dès que le reste passe sous le minimum, marge comprise', () => {
    const deadline = createPipelineDeadline(0);
    // 250 s consommées : 50 s restantes, donc 35 s utilisables — sous les 45 s
    // minimales du routage. Lancer l'appel serait le condamner d'avance.
    expect(() => deadline.budgetFor('routing', 250_000)).toThrow(PipelineBudgetExceededError);
  });

  it('accorde le plafond nominal quand le temps restant le permet', () => {
    const deadline = createPipelineDeadline(0);
    expect(deadline.budgetFor('placement', 0)).toBe(STEP_CAP_MS.placement);
  });

  it('refuse de lancer une étape qui ne peut pas tenir dans le temps restant', () => {
    const deadline = createPipelineDeadline(0);
    // 295 s consommées : il reste moins que le minimum du routage.
    expect(() => deadline.budgetFor('routing', 295_000)).toThrow(PipelineBudgetExceededError);
  });

  it('nomme l étape et le temps restant dans l erreur', () => {
    const deadline = createPipelineDeadline(0);
    try {
      deadline.budgetFor('routing', 299_000);
      expect.unreachable('aurait dû refuser');
    } catch (err) {
      expect(err).toBeInstanceOf(PipelineBudgetExceededError);
      expect((err as Error).message).toContain('routing');
    }
  });

  it('remainingMs décroît avec le temps écoulé et ne passe jamais sous zéro', () => {
    const deadline = createPipelineDeadline(1_000);
    expect(deadline.remainingMs(1_000)).toBe(INVOCATION_BUDGET_MS);
    expect(deadline.remainingMs(101_000)).toBe(INVOCATION_BUDGET_MS - 100_000);
    expect(deadline.remainingMs(999_000)).toBe(0);
  });
});
