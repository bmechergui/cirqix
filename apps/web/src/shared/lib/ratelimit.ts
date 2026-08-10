import { Ratelimit } from '@upstash/ratelimit';
import { Redis } from '@upstash/redis';

// ---------------------------------------------------------------------------
// Rate limiting Upstash (PLAN.md §5.1)
//
// Fail-open si UPSTASH_REDIS_REST_URL/TOKEN sont absents : le dev local n'a
// pas de Redis Upstash, et bloquer les requêtes sur une config manquante
// transformerait une coupure Upstash en panne totale. Le warning n'est logué
// qu'une fois par process. En prod, poser les deux variables active la
// protection sans changement de code.
//
// Câblage actuel :
//   · /api/waitlist — endpoint public, quota par IP, 10 req/min (défaut).
//   · /api/agent    — quota par UTILISATEUR, 3 req/60 s (issue #117). Il borne
//     la CADENCE d'allumage, pas la simultanéité : la fenêtre fixe se remet à
//     zéro chaque minute, donc un compte peut tenir 15 pipelines en vol sur les
//     300 s d'un run. Le calcul est dans app/api/agent/lib/rate-limit.ts
//     (`worstCaseConcurrentPipelines`), verrouillé par un test.
//
// Le fail-open ci-dessous vaut aussi pour /api/agent : une panne Upstash y
// rouvre la porte. C'est pourquoi ce quota ne clôt pas #117 — il borne le
// débit d'allumage, il ne réserve pas de crédits.
// ---------------------------------------------------------------------------

export interface RateLimitResult {
  success: boolean;
  remaining: number;
}

const limiters = new Map<string, Ratelimit>();
let warnedFailOpen = false;

function getLimiter(limit: number, windowSeconds: number): Ratelimit | null {
  const url = process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;

  const cacheKey = `${limit}:${windowSeconds}`;
  let limiter = limiters.get(cacheKey);
  if (!limiter) {
    limiter = new Ratelimit({
      redis: new Redis({ url, token }),
      limiter: Ratelimit.fixedWindow(limit, `${windowSeconds} s`),
      analytics: false,
    });
    limiters.set(cacheKey, limiter);
  }
  return limiter;
}

/**
 * Vérifie le quota d'un identifiant (ex. `waitlist:1.2.3.4`).
 * Défaut PLAN : 10 requêtes / 60 s.
 */
export async function checkRateLimit(
  identifier: string,
  limit = 10,
  windowSeconds = 60,
): Promise<RateLimitResult> {
  const limiter = getLimiter(limit, windowSeconds);
  if (!limiter) {
    if (!warnedFailOpen) {
      console.warn('[ratelimit] UPSTASH_REDIS_REST_URL/TOKEN absents — limiter désactivé (fail-open)');
      warnedFailOpen = true;
    }
    return { success: true, remaining: limit };
  }
  const res = await (async () => {
    try {
      return await limiter.limit(identifier);
    } catch (err) {
      // Coupure/timeout Upstash : fail-open cohérent avec le cas « env
      // absentes » — une panne Upstash ne doit pas devenir une panne totale.
      console.warn('[ratelimit] Upstash injoignable, requête admise (fail-open):', err);
      return { success: true, remaining: limit };
    }
  })();
  return { success: res.success, remaining: res.remaining };
}
