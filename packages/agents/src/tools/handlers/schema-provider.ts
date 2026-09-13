/**
 * Qui écrit le schéma quand l'utilisateur n'en fournit pas.
 *
 * `haiku` (défaut) : l'API Anthropic, comme depuis la Phase 2.
 * `claude-code` : Claude Code en ligne de commande (`claude -p`), décision
 * D-2026-09-13-a — le solde de l'API est épuisé, l'abonnement Claude Code ne
 * l'est pas, et Claude Code a déjà écrit deux schémas livrés à 100 %
 * (`examples/driver-clignotant-ne555`, `examples/driver-stm32-minimal`).
 *
 * ⚠️ Échoue FERMÉ sur une valeur inconnue : un fournisseur mal orthographié
 * retombe sur Haiku, jamais sur un chemin qu'on n'a pas voulu.
 */
export type SchemaProvider = 'haiku' | 'claude-code';

export function schemaProvider(env: Record<string, string | undefined>): SchemaProvider {
  const brut = (env['CIRQIX_SCHEMA_PROVIDER'] ?? '').trim().toLowerCase();
  return brut === 'claude-code' ? 'claude-code' : 'haiku';
}
