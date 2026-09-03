/**
 * Bascule vers le pipeline asynchrone.
 *
 * Le client a basculé : un `202 {runId}` est suivi via Realtime (sondage en
 * repli). La route peut donc répondre `202` dès que ce drapeau est allumé.
 *
 * Il échoue FERMÉ, délibérément : toute valeur non explicitement affirmative
 * laisse le SSE synchrone (plafond 300 s). Un drapeau mal orthographié doit
 * être sans effet, jamais activer en silence un chemin qui exige Redis + worker.
 */

/** Valeurs reconnues comme un « oui ». Volontairement courtes et strictes. */
const AFFIRMATIVE = new Set(['1', 'true']);

export interface AsyncModeOptions {
  /**
   * Exiger `REDIS_URL`. Sans file, un job enfilé ne serait consommé par
   * personne : l'utilisateur verrait sa demande acceptée (`202`) puis jamais
   * traitée — pire qu'un refus franc.
   */
  requireRedis?: boolean;
}

export function asyncPipelineEnabled(
  env: Record<string, string | undefined>,
  options: AsyncModeOptions = {},
): boolean {
  if (!AFFIRMATIVE.has(env['CIRQIX_ASYNC_PIPELINE'] ?? '')) return false;
  if (options.requireRedis && !env['REDIS_URL']) return false;
  return true;
}
