/**
 * Transport HTTP des appels LONGS vers le service KiCad.
 *
 * ⚠️ Le `fetch` global de Node (undici) impose sa PROPRE échéance, invisible
 * dans le code appelant : `headersTimeout` et `bodyTimeout` valent 300 000 ms
 * par défaut. Un `AbortSignal.timeout(3_600_000)` ne les désarme pas — ce sont
 * deux mécanismes distincts. Toute requête dont la réponse met plus de 5 minutes
 * à commencer échoue donc avec `UND_ERR_HEADERS_TIMEOUT`, quel que soit le
 * budget accordé au serveur.
 *
 * C'est un CINQUIÈME plafond de 300 s, à l'intérieur de Node lui-même, sous les
 * quatre déjà corrigés (client, validation HTTP, câblage du budget, routeur).
 * Il explique aussi pourquoi le nombre 300 s semblait venir de Vercel : la
 * plateforme et undici imposent la même valeur, pour des raisons sans rapport.
 *
 * Mesuré le 2026-08-20 : le routage du board STM32 de
 * `examples/stm32-validation` envoyé avec `timeout_s: 1800` meurt côté client
 * sur `UND_ERR_HEADERS_TIMEOUT` — le service, lui, continuait de router.
 *
 * Le service KiCad n'émet ses en-têtes qu'une fois le travail terminé : sur un
 * routage de 15-20 minutes, la connexion reste donc silencieuse tout du long.
 * C'est le mode NORMAL de ces appels, pas un incident — d'où la mise à zéro
 * (= désarmé) des deux échéances de transport.
 *
 * La vraie limite reste l'`AbortSignal` passé par l'appelant : une échéance
 * explicite, choisie et mesurée, au lieu d'un défaut de librairie.
 *
 * Garde : tests/long-call-transport.test.ts.
 */

import { Agent, fetch as undiciFetch } from 'undici';

/** 0 = désarmé. Le serveur peut rester muet aussi longtemps qu'il travaille. */
export const LONG_CALL_HEADERS_TIMEOUT_MS = 0;
/** 0 = désarmé. Idem pour la lecture du corps (un `.kicad_pcb` complet). */
export const LONG_CALL_BODY_TIMEOUT_MS = 0;

let dispatcher: Agent | undefined;

/**
 * Dispatcher partagé.
 *
 * Un seul suffit : il gère son pool de connexions. En créer un par appel
 * fuirait des sockets sur un pipeline qui enchaîne les étapes.
 */
export function longCallDispatcher(): Agent {
  dispatcher ??= new Agent({
    headersTimeout: LONG_CALL_HEADERS_TIMEOUT_MS,
    bodyTimeout: LONG_CALL_BODY_TIMEOUT_MS,
  });
  return dispatcher;
}

/**
 * `fetch` pour un appel qui peut durer des dizaines de minutes.
 *
 * `undiciFetch` et `Agent` viennent du MÊME paquet : mélanger le `fetch` global
 * de Node avec un dispatcher d'une autre version d'undici n'est pas un contrat
 * garanti.
 *
 * Le type de retour est celui du DOM : les appelants ne lisent que `ok`,
 * `status`, `text()` et `json()`, identiques dans les deux implémentations.
 */
export async function longCallFetch(
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal },
): Promise<Response> {
  const response = await undiciFetch(url, {
    method: init.method,
    headers: init.headers,
    body: init.body,
    ...(init.signal ? { signal: init.signal } : {}),
    dispatcher: longCallDispatcher(),
  });
  return response as unknown as Response;
}
