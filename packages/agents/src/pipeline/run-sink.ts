/**
 * Contrat de sortie d'un run de pipeline.
 *
 * Le pipeline émettait jusqu'ici directement dans un flux SSE :
 *
 *     controller.enqueue(encoder.encode(encodeSse(ev)))
 *
 * — c'est-à-dire dans un `ReadableStreamDefaultController` de Next.js. Cette
 * dépendance est ce qui CLOUE le pipeline à l'invocation web : on ne peut pas
 * l'exécuter dans un worker sans un contrôleur de flux qui n'existe pas là-bas.
 *
 * Or l'invocation est plafonnée (`maxDuration = 300`) alors qu'un routage réel
 * dure 861 s (mesuré le 2026-08-19 sur le board STM32). Le pipeline doit donc
 * sortir de la requête — et pour cela, cesser de savoir COMMENT ses événements
 * voyagent.
 *
 * `RunSink` est cette frontière. Le pipeline émet ; le porteur décide du
 * transport :
 *
 *   - `SseSink` (apps/web)  — le flux actuel, comportement inchangé ;
 *   - `PgSink`  (étape 3)   — INSERT dans `pcb_run_events`, lu par le navigateur
 *                             en Supabase Realtime. Le worker n'a alors besoin
 *                             d'aucune surface réseau, et un rechargement de
 *                             page rejoue l'historique.
 *
 * `emit` est asynchrone À DESSEIN : l'écriture SSE est synchrone, mais un INSERT
 * ne l'est pas. Rendre la signature asynchrone dès maintenant évite d'avoir à
 * réécrire tous les sites d'appel à l'étape 3.
 */

import type { AgentStep, PCBState, PCBStatus } from '@cirqix/types';

/**
 * Événement de progression d'un run.
 *
 * Forme identique à l'ancien `SseEvent` d'`apps/web` — le type déménage ici
 * parce que c'est le pipeline qui le PRODUIT, pas le transport qui le définit.
 */
export type RunEvent =
  | { type: 'token'; content: string }
  | { type: 'step'; step: AgentStep }
  | { type: 'status'; status: PCBStatus }
  | { type: 'pcb_state'; state: PCBState }
  | { type: 'reasoning'; steps: string[] }
  | { type: 'error'; message: string }
  | { type: 'done' };

/** Destination des événements d'un run. Le pipeline ignore laquelle. */
export interface RunSink {
  emit(event: RunEvent): Promise<void>;
}
