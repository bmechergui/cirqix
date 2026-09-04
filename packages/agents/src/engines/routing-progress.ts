/**
 * Progression du routage — la mesure que le service faisait déjà sans la dire.
 *
 * `_route_with_freerouting_api` relit le journal de la JVM toutes les deux
 * secondes et en tire le numéro de passe et le nombre de nets non routés. Cette
 * mesure servait uniquement, en interne, à couper l'attente d'un job figé : elle
 * ne sortait pas du service. L'utilisateur voyait « routage en cours » pendant
 * vingt minutes alors que le routeur savait à chaque instant où il en était.
 *
 * ⚠️ CE N'EST QU'UN AFFICHAGE, JAMAIS UN VERDICT. Aucune de ses pannes ne doit
 * interrompre un routage déjà payé : service muet, 500, JSON illisible, sink en
 * panne — tout se lit « rien à afficher ». Un pourcentage manquant est un
 * désagrément ; une carte perdue parce que son indicateur a levé serait une
 * faute. C'est le pendant exact du fail-fast des handlers, dans l'autre sens :
 * là où un résultat FABRIQUÉ est interdit, une mesure ABSENTE est acceptable.
 *
 * Garde : `tests/routing-progress.test.ts`.
 */
import pino from 'pino';

import { buildKicadServiceHeaders } from './kicad-service-auth';

const log = pino({ name: 'routing-progress' });

/** Avancement d'un routage, tel que le service vient de le publier. */
export interface RoutingProgress {
  /** Numéro de la dernière passe journalisée par Freerouting. */
  pass: number;
  /** Nets qu'il reste à relier. */
  unrouted: number;
  /** Nets routables du board d'entrée — le dénominateur de la mesure. */
  nets: number;
  /** Palier de couches en cours d'essai. */
  layers: number;
  /** Nets reliés, en pourcentage. Calculé par le service, pas ici. */
  percent: number;
}

interface ServiceProgressBody {
  connu?: unknown;
  passe?: unknown;
  non_routes?: unknown;
  nets?: unknown;
  palier?: unknown;
  pourcentage?: unknown;
}

/**
 * Alphabet accepte par le service pour nommer une progression.
 *
 * ⚠️ Le service REFUSE une cle hors de cet alphabet, en 422 — a raison : elle
 * nomme un fichier chez lui. Mais ce refus tomberait sur `POST /route/auto`,
 * c est-a-dire sur LE ROUTAGE, pour un simple indicateur d avancement. On
 * verifie donc ici, et on renonce a l affichage plutot que de risquer la carte.
 */
const CLE_ACCEPTEE = /^[A-Za-z0-9_-]{1,128}$/;

/**
 * Cle de progression pour `id`, ou `undefined` si le service la refuserait.
 *
 * `undefined` se propage naturellement : la requete de routage part sans cle,
 * le service ne publie rien, le sondeur ne demarre pas. Personne n echoue.
 */
export function progressKeyFor(id: string): string | undefined {
  return CLE_ACCEPTEE.test(id) ? id : undefined;
}

/** Sondage par défaut. Le routeur, lui, relit son journal toutes les 2 s. */
export const PROGRESS_POLL_MS = 5_000;

function entier(valeur: unknown): number {
  return typeof valeur === 'number' && Number.isFinite(valeur) ? Math.trunc(valeur) : 0;
}

/**
 * Dernière progression publiée pour `key`, ou `null`.
 *
 * `null` couvre trois situations que l'appelant n'a pas à distinguer : le
 * routeur n'a pas encore publié sa première passe, le service est injoignable,
 * la réponse est illisible. Aucune n'appelle d'action de sa part.
 */
export async function readRoutingProgress(
  key: string,
): Promise<RoutingProgress | null> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) return null;

  const url = `${baseUrl.replace(/\/+$/, '')}/route/progress/${encodeURIComponent(key)}`;
  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: buildKicadServiceHeaders(),
    });
    if (!response.ok) return null;

    const body = (await response.json()) as ServiceProgressBody;
    if (body.connu !== true) return null;

    return {
      pass: entier(body.passe),
      unrouted: entier(body.non_routes),
      nets: entier(body.nets),
      layers: entier(body.palier),
      percent: entier(body.pourcentage),
    };
  } catch {
    return null;
  }
}

export interface FollowRoutingProgressOptions {
  /** Nom sous lequel le routage publie son avancement. */
  key: string;
  /** Appelé à chaque AVANCÉE — jamais deux fois pour la même mesure. */
  onProgress: (progress: RoutingProgress) => void | Promise<void>;
  /** Arrête le suivi. Attendu : la fin de l'étape de routage. */
  signal: AbortSignal;
  intervalMs?: number;
}

function identique(a: RoutingProgress | null, b: RoutingProgress): boolean {
  return (
    a !== null &&
    a.pass === b.pass &&
    a.unrouted === b.unrouted &&
    a.layers === b.layers
  );
}

/**
 * Sonde `key` jusqu'à l'abandon du signal, en signalant chaque avancée.
 *
 * ⚠️ Les répétitions sont tues. Le routeur republie à chaque sondage même
 * quand il n'avance pas : `stm32-100` a produit 995 passes identiques après
 * la quatrième. Les réémettre remplirait le journal du run de lignes qui
 * n'apprennent rien, et le navigateur les rejouerait toutes au rattrapage.
 *
 * Ne rejette jamais : la promesse se résout à l'arrêt, quoi qu'il soit arrivé.
 */
export async function followRoutingProgress({
  key,
  onProgress,
  signal,
  intervalMs = PROGRESS_POLL_MS,
}: FollowRoutingProgressOptions): Promise<void> {
  let dernier: RoutingProgress | null = null;

  while (!signal.aborted) {
    const vu = await readRoutingProgress(key);
    if (vu !== null && !identique(dernier, vu)) {
      dernier = vu;
      try {
        await onProgress(vu);
      } catch (err) {
        // Le sink peut être momentanément indisponible. Perdre une ligne
        // d'affichage est sans conséquence ; perdre le suivi d'un routage de
        // vingt minutes ne l'est pas.
        log.warn({ err, key }, 'progression non transmise — suivi conservé');
      }
    }
    if (signal.aborted) break;
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, intervalMs);
      signal.addEventListener(
        'abort',
        () => {
          clearTimeout(timer);
          resolve();
        },
        { once: true },
      );
    });
  }
}
