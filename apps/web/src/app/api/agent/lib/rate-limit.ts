/**
 * Quota d'allumage du pipeline agent (issue #117).
 *
 * `POST /api/agent` lit le solde, appelle `hasEnoughPipelineCredits`, puis
 * lance un pipeline qui peut tourner 300 s ; le débit n'arrive qu'à la fin,
 * dans `finalize_pipeline_success`. Entre les deux, rien n'est réservé :
 * plusieurs requêtes lancées ensemble lisent le même solde et passent toutes
 * le contrôle. Le débit final reste exact — ce n'est pas un vol de crédits —
 * mais chaque pipeline consomme Sonnet, le service KiCad et Freerouting.
 *
 * Ce quota borne la CADENCE D'ALLUMAGE, pas le nombre de pipelines simultanés.
 * La distinction n'est pas cosmétique — voir `worstCaseConcurrentPipelines`.
 *
 * Il ne remplace pas une réservation durable : `checkRateLimit` est fail-open
 * (une panne Upstash laisse tout passer, choix assumé côté `shared/lib`), et
 * un quota par fenêtre ne sait rien du solde. La réservation reste à écrire.
 */

/**
 * 3 démarrages par fenêtre. Un pipeline dure de 30 à 300 s : un utilisateur
 * légitime n'en allume pas plus de deux par minute, et le troisième laisse la
 * marge d'un réessai après un échec rapide.
 */
export const AGENT_RATE_LIMIT = 3;

/** Fenêtre du compteur, en secondes. */
export const AGENT_RATE_WINDOW_S = 60;

/**
 * Nombre de pipelines qu'un SEUL compte peut avoir en vol simultanément en
 * régime soutenu — la borne réelle, qui n'est pas `AGENT_RATE_LIMIT`.
 *
 * `Ratelimit.fixedWindow` remet son compteur à zéro à chaque fenêtre. Un compte
 * qui tient la cadence maximale traverse `maxDuration / fenêtre` fenêtres avant
 * que le premier pipeline ne s'achève, et en allume `AGENT_RATE_LIMIT` à
 * chacune : 300 s / 60 s = 5 fenêtres × 3 = **15 pipelines encore actifs**.
 * S'y ajoute l'effet de bord classique de la fenêtre fixe — jusqu'à 6
 * démarrages en deux secondes, à cheval sur deux fenêtres.
 *
 * 15 n'est pas 3, mais 15 est borné et l'état précédent ne l'était pas. Borner
 * réellement la simultanéité demanderait un verrou par utilisateur tenu pendant
 * toute la durée du run, pas un compteur par fenêtre — c'est le fond de #117.
 */
export function worstCaseConcurrentPipelines(maxDurationSeconds: number): number {
  return Math.ceil(maxDurationSeconds / AGENT_RATE_WINDOW_S) * AGENT_RATE_LIMIT;
}

/**
 * Le quota est nominatif. Une clé IP punirait tout un réseau d'entreprise pour
 * un seul abus, et laisserait passer un abus réparti sur plusieurs adresses.
 */
export function agentRateLimitKey(userId: string): string {
  return `agent:${userId}`;
}
