import * as Sentry from '@sentry/nextjs';
import { scrubEvent } from './sentry-scrub';

/**
 * Initialisation Sentry — appelée par `instrumentation.ts`.
 *
 * DÉSACTIVÉ PAR DÉFAUT. Sans `SENTRY_DSN`, `init()` n'est jamais appelé et le
 * SDK reste inerte : aucun réseau, aucune donnée qui sort. Même contrat que le
 * limiteur Upstash — une intégration d'observabilité absente ne doit jamais
 * empêcher l'application de tourner, en développement comme en CI.
 *
 * Le point important de ce fichier n'est pas `init()`, c'est `beforeSend` : il
 * expurge chaque événement AVANT qu'il ne quitte le process. Voir
 * `sentry-scrub.ts` pour ce qui est retiré et pourquoi.
 */
export function initSentry(): void {
  const dsn = process.env['SENTRY_DSN'];
  if (!dsn) return;

  Sentry.init({
    dsn,
    environment: process.env['VERCEL_ENV'] ?? process.env['NODE_ENV'] ?? 'development',
    release: process.env['VERCEL_GIT_COMMIT_SHA'],

    // Pas de traces de performance : elles attachent des URLs, des corps de
    // requête et des requêtes SQL, donc une surface d'exfiltration bien plus
    // large — pour un besoin que nous n'avons pas. Ce qu'on cherche ici, ce
    // sont les erreurs que la production avalait en silence.
    tracesSampleRate: 0,

    // Les données personnelles par défaut (IP, en-têtes, cookies) n'aident pas
    // à diagnostiquer un pipeline PCB.
    sendDefaultPii: false,

    // Dernière barrière avant l'envoi. Si elle jette, l'événement est
    // abandonné plutôt qu'envoyé non filtré : perdre une alerte est moins grave
    // qu'exfiltrer un schéma client.
    beforeSend(event) {
      try {
        return scrubEvent(event);
      } catch {
        return null;
      }
    },

    // Les fils d'Ariane transportent des URLs et des corps de requête ; ils
    // passent par le même filtre.
    beforeBreadcrumb(breadcrumb) {
      try {
        return scrubEvent(breadcrumb);
      } catch {
        return null;
      }
    },
  });
}
