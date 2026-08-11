/**
 * Nettoyage des événements avant envoi à Sentry.
 *
 * POURQUOI CE FICHIER EXISTE
 *
 * Sentry est un service TIERS. Tout ce qu'on lui envoie quitte notre
 * infrastructure. Or le pipeline Cirqix manipule, à chaque étape, de la
 * propriété intellectuelle du client :
 *
 *   - `prompt`            — la description du circuit, souvent le produit lui-même ;
 *   - `kicad_sch_content` — le schéma complet ;
 *   - `kicad_pcb_content` — le board, empreintes et pistes comprises ;
 *   - `gerber_zip_b64`    — les fichiers de fabrication ;
 *   - `bom_csv`           — la nomenclature, donc les fournisseurs et les coûts.
 *
 * L'assistant d'installation Sentry attache volontiers le contexte disponible.
 * Sans le filtre ci-dessous, une simple erreur de routage exfiltrerait le
 * circuit d'un client vers un tiers — sans qu'aucun test, aucune CI et aucune
 * revue ne le signale, puisque tout continuerait de fonctionner.
 *
 * DEUX BARRIÈRES, VOLONTAIREMENT REDONDANTES
 *
 *  1. Par NOM de champ — précis, mais aveugle à ce qui n'existe pas encore.
 *     Un champ ajouté dans six mois ne serait pas dans la liste.
 *  2. Par TAILLE — toute chaîne anormalement longue est tronquée, quel que soit
 *     son nom. Les blobs qui comptent (schéma, board, Gerbers, base64) font des
 *     dizaines de kilo-octets ; un message d'erreur utile en fait quelques
 *     centaines. La deuxième barrière rattrape donc ce que la première ignore.
 *
 * Ce qui est CONSERVÉ, parce que c'est ce qui rend une alerte exploitable :
 * type et message d'erreur, pile d'appels, `projectId`, `userId` (UUID
 * pseudonyme), nom de l'étape, codes HTTP et SQLSTATE.
 */

/**
 * Motifs cherchés en SOUS-CHAÎNE dans les noms de champs, pas en égalité.
 *
 * L'égalité exacte a été mesurée insuffisante le 2026-08-12 sur le service
 * Python : elle listait les noms de champs de l'API (`kicad_pcb_b64`…) alors
 * que les VARIABLES du code s'appellent `pcb_bytes`, `zip_bytes`,
 * `pcb_content`. Aucune ne correspondait, et le board partait en entier.
 *
 * Une liste de noms exacts ne peut pas suivre le nommage réel d'un code qui
 * évolue. Le même durcissement est appliqué ici par symétrie, avant que le
 * défaut n'apparaisse de ce côté.
 */
const REDACTED_PATTERNS = [
  'prompt',
  'b64',
  'content',
  'gerber',
  'bom',
  'cpl',
  'schema',
  'netlist',
  'simulation',
  'pcbstate',
  'pcb_state',
  // Secrets — ne devraient jamais transiter, mais le coût d'un oubli est trop
  // élevé pour se fier à cette conviction.
  'authorization',
  'cookie',
  'token',
  'secret',
  'api_key',
  'apikey',
  'password',
  'user_sig',
];

function isSensitiveKey(key: string): boolean {
  const k = key.toLowerCase();
  return REDACTED_PATTERNS.some((p) => k.includes(p));
}

/**
 * Au-delà de cette longueur, une chaîne est tronquée quel que soit son nom.
 * Un message d'erreur exploitable tient largement en dessous ; les charges
 * utiles KiCad font des dizaines de kilo-octets.
 */
export const MAX_STRING_LENGTH = 512;

/** Profondeur maximale explorée — garde contre les structures cycliques. */
const MAX_DEPTH = 8;

export const REDACTED = '[expurgé]';

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * Expurge récursivement une valeur destinée à Sentry.
 *
 * Immuable : ne modifie jamais l'entrée, renvoie une copie nettoyée. Muter
 * l'événement en place corromprait l'objet que l'application continue
 * d'utiliser après l'envoi.
 */
export function scrubValue(value: unknown, depth = 0): unknown {
  if (depth > MAX_DEPTH) return REDACTED;

  if (typeof value === 'string') {
    return value.length > MAX_STRING_LENGTH
      ? `${value.slice(0, MAX_STRING_LENGTH)}… [tronqué, ${value.length} caractères]`
      : value;
  }

  if (Array.isArray(value)) {
    return value.map((v) => scrubValue(v, depth + 1));
  }

  if (isPlainObject(value)) {
    const out: Record<string, unknown> = {};
    for (const [key, v] of Object.entries(value)) {
      out[key] = isSensitiveKey(key) ? REDACTED : scrubValue(v, depth + 1);
    }
    return out;
  }

  return value;
}

/**
 * `beforeSend` : dernière barrière avant que l'événement ne quitte le process.
 *
 * Générique volontairement : la fonction préserve la forme qu'elle reçoit, ce
 * qui évite aux appelants — dont les types Sentry `ErrorEvent` et `Breadcrumb`
 * — un transtypage à chaque site d'appel. Un `as unknown as` répété finit
 * toujours par masquer une vraie incompatibilité.
 *
 * Les en-têtes et cookies de requête sont supprimés en bloc plutôt qu'expurgés
 * champ par champ : ils ne portent rien qu'une alerte exige, et tout ce qu'un
 * jeton d'authentification ne doit pas quitter.
 */
export function scrubEvent<T extends object>(event: T): T {
  const scrubbed = scrubValue(event) as Record<string, unknown>;

  const request = scrubbed['request'];
  if (isPlainObject(request)) {
    const { headers: _h, cookies: _c, ...rest } = request;
    scrubbed['request'] = rest;
  }

  return scrubbed as T;
}
