/**
 * Hook d'instrumentation Next.js — exécuté une fois au démarrage du serveur.
 *
 * Sentry n'est initialisé que côté serveur (Node et Edge). Le navigateur en est
 * volontairement exclu : le viewer y détient le schéma et le board complets, et
 * un SDK client attache le contexte de la page à ses événements. Le risque
 * d'exfiltration serait maximal là où le bénéfice est minimal — les défauts que
 * ce projet a passé sa journée à corriger vivaient tous côté serveur, dans des
 * chemins d'erreur silencieux.
 */
export async function register(): Promise<void> {
  if (process.env['NEXT_RUNTIME'] === 'nodejs' || process.env['NEXT_RUNTIME'] === 'edge') {
    const { initSentry } = await import('./shared/lib/sentry-init');
    initSentry();
  }
}
