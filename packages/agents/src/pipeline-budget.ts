/**
 * Budget d'invocation du pipeline — source unique des échéances.
 *
 * `apps/web/src/app/api/agent/route.ts` exporte `maxDuration = 300`. C'est un
 * plafond d'HORLOGE MURALE que la plateforme applique à l'invocation entière,
 * pas un budget de CPU : `await` libère la boucle d'événements de Node, il ne
 * rend pas la main à la plateforme. La fonction reste ouverte tant qu'elle tient
 * le flux SSE — qu'elle calcule ou qu'elle attende un `fetch` au service KiCad.
 *
 * Ce que ce module corrige (mesuré) :
 *
 *   1. `ROUTING_TIMEOUT_MS = 330_000` dépassait `maxDuration` de 30 s. Le
 *      garde-fou `AbortSignal.timeout(330_000)` ne pouvait JAMAIS se déclencher
 *      en production : la plateforme tuait la fonction 30 s plus tôt. Un filet
 *      de sécurité inatteignable est le signe que deux budgets n'ont jamais été
 *      confrontés.
 *   2. Le service Python s'accorde `_ROUTE_TIMEOUT_S = 600`
 *      (`services/kicad/tools/kct_route.py`), soit le double de l'invocation qui
 *      l'attend. Le routage continue côté conteneur pendant que l'appelant est
 *      déjà mort : travail perdu, flux SSE coupé net, aucun message d'erreur.
 *
 * Ce module ne « re-règle » PAS les plafonds pour les faire tenir : placement
 * (180 s) + routage (330 s) valent 510 s à eux seuls. Aucun jeu de constantes
 * fixes ne rentre dans 300 s, et prétendre le contraire ne ferait que déplacer
 * le mensonge. Il impose une échéance VÉRIFIÉE avant chaque étape longue :
 *
 *   - le plafond accordé est raboté sur le temps réellement restant ;
 *   - si le reste ne couvre même pas le minimum de l'étape, on refuse de la
 *     lancer et on lève `PipelineBudgetExceededError` — le pipeline échoue
 *     honnêtement, dans le budget, au lieu d'être tué en vol.
 *
 * `RESPONSE_MARGIN_MS` est ce qui rend l'échec racontable : il réserve de quoi
 * émettre l'erreur et vider le flux SSE avant que la plateforme ne coupe.
 *
 * La vraie levée du plafond est architecturale (job asynchrone : la route
 * accepte, empile, un worker persistant exécute sans plafond). Tant que le
 * pipeline tourne DANS l'invocation, ce module est la garantie qu'il en
 * respecte les limites au lieu de les ignorer.
 */

/**
 * Doit rester égal à `maxDuration` dans `apps/web/src/app/api/agent/route.ts`.
 * Toute divergence recrée exactement le bug du garde-fou inatteignable.
 */
export const INVOCATION_BUDGET_MS = 300_000;

/** Réservé pour signaler l'erreur et vider le flux SSE avant la coupure. */
export const RESPONSE_MARGIN_MS = 15_000;

/** Étapes dont la durée justifie une vérification d'échéance. */
export type BudgetedStep = 'placement' | 'routing' | 'reason' | 'drc' | 'export';

/**
 * Plafond nominal par étape — jamais dépassé, mais raboté si le temps restant
 * est plus court. Chaque valeur tient dans `INVOCATION_BUDGET_MS` moins la
 * marge : c'est l'invariant que `pipeline-budget.test.ts` verrouille.
 */
export const STEP_CAP_MS: Record<BudgetedStep, number> = {
  placement: 180_000,
  routing: 240_000,
  reason: 120_000,
  drc: 30_000,
  export: 60_000,
};

/**
 * En deçà, lancer l'étape est un gâchis : l'appel partirait pour être annulé
 * avant d'avoir pu produire quoi que ce soit d'exploitable.
 */
export const STEP_MINIMUM_MS: Record<BudgetedStep, number> = {
  placement: 30_000,
  routing: 45_000,
  reason: 20_000,
  drc: 10_000,
  export: 15_000,
};

/** Le temps restant ne permet plus de lancer cette étape honnêtement. */
export class PipelineBudgetExceededError extends Error {
  constructor(
    readonly step: BudgetedStep,
    readonly remainingMs: number,
  ) {
    super(
      `Budget d'invocation épuisé avant l'étape « ${step} » : ` +
        `${Math.max(0, Math.round(remainingMs / 1000))}s restantes, ` +
        `${Math.round(STEP_MINIMUM_MS[step] / 1000)}s minimum requises.`,
    );
    this.name = 'PipelineBudgetExceededError';
  }
}

export interface PipelineDeadline {
  /** Millisecondes restantes dans l'invocation, jamais négatif. */
  remainingMs(now?: number): number;
  /**
   * Budget à accorder à `step`, raboté sur le temps restant.
   * @throws {PipelineBudgetExceededError} si le reste ne couvre pas le minimum.
   */
  budgetFor(step: BudgetedStep, now?: number): number;
}

/**
 * Ouvre une échéance à l'entrée du pipeline. `startedAt` est injectable pour
 * que les tests raisonnent sur une horloge déterministe.
 */
export function createPipelineDeadline(startedAt: number = Date.now()): PipelineDeadline {
  const endsAt = startedAt + INVOCATION_BUDGET_MS;

  const remainingMs = (now: number = Date.now()): number => Math.max(0, endsAt - now);

  return {
    remainingMs,
    budgetFor(step: BudgetedStep, now: number = Date.now()): number {
      const usable = remainingMs(now) - RESPONSE_MARGIN_MS;
      if (usable < STEP_MINIMUM_MS[step]) {
        throw new PipelineBudgetExceededError(step, remainingMs(now));
      }
      return Math.min(STEP_CAP_MS[step], usable);
    },
  };
}
