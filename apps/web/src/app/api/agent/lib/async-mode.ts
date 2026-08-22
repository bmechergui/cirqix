/**
 * Bascule vers le pipeline asynchrone.
 *
 * La route et le client doivent basculer ENSEMBLE : passer la route en `202`
 * pendant que le client attend un flux SSE casserait l'application pour tous les
 * utilisateurs. Ce drapeau permet de livrer les deux chemins, de valider
 * l'asynchrone sur un environnement réel, puis de changer le défaut.
 *
 * Il échoue FERMÉ, délibérément : toute valeur non explicitement affirmative
 * laisse le comportement actuel. Un drapeau mal orthographié doit être sans
 * effet, jamais activer en silence un chemin non validé.
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
