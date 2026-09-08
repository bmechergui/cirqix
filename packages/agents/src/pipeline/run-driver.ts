/**
 * La chaîne du driver — le pipeline complet SANS le moindre appel au modèle.
 *
 * ## Pourquoi elle existe
 *
 * Le solde de l'API Anthropic est épuisé depuis le 2026-09-06 (`400
 * invalid_request_error`, « Your credit balance is too low »). L'orchestrateur
 * étant la toute première étape, plus aucun PCB ne peut aboutir par la voie
 * normale — ce n'est pas un défaut de code, mais le résultat est le même :
 * le produit est à l'arrêt.
 *
 * Or `call_agent_schema` est le SEUL maillon de la chaîne qui appelle un
 * modèle. Tout le reste — ERC, gen_pcb, placement, routage, DRC, export — est
 * déterministe, et le banc des dix cartes l'a mesuré jusqu'aux Gerbers :
 * 5 à 70 composants, 100 % routées, zéro erreur de fabricabilité.
 *
 * Ce porteur enchaîne donc les VRAIS handlers, dans l'ordre du pipeline, à
 * partir d'un schéma écrit par le driver.
 *
 * ## Ce que ce n'est PAS
 *
 * ⚠️ Ce n'est pas le simulateur. `apps/web/.../simulator.ts` FABRIQUE des états ;
 * ici tout est réel — vrai `.kicad_sch`, vrai board, vrai DRC, vrais Gerbers.
 * Ce qui change est la PROVENANCE du schéma, pas la qualité du résultat.
 *
 * ⚠️ Et c'est pourquoi ces boards restent NON COMMANDABLES :
 * `POST /api/jlcpcb/order` exige `agent_mode === 'orchestrator'` et échoue
 * fermé sur toute autre provenance. « Inconnu » n'est pas « vérifié », et un
 * schéma écrit à la main n'a pas traversé la boucle autonome que le produit
 * vend. Ne PAS assouplir ce gate pour faire passer un board du driver.
 *
 * ## Pourquoi une source d'événements, et pas un second pipeline
 *
 * Ce module rend un `AsyncGenerator<SSEEvent>` de la MÊME forme que
 * `runOrchestrator`. `runOrchestratorPipeline` le consomme sans rien savoir de
 * lui : dépôt des artefacts, fusion d'état, persistance, suivi du routage,
 * finalisation et facturation restent écrits UNE fois.
 *
 * Dupliquer ces deux cents lignes aurait créé un second chemin à corriger à
 * chaque fois — et ce dépôt a déjà payé ce prix : `local-pipeline.ts` écrivait
 * un statut CODÉ EN DUR par étape et persistait `DRC_CLEAN` sur un DRC en
 * erreur, parce qu'il redisait à sa façon ce que les handlers disaient déjà.
 */

import { executeToolStub } from '../tools';
import { log } from '../tools/shared';
import type { SSEEvent } from '../orchestrator';

export interface DriverOptions {
  /** Le schéma écrit par le driver : composants, nets, et dimensions de carte. */
  schema: Record<string, unknown>;
  projectId: string;
}

/**
 * Une étape de la chaîne.
 *
 * `ui` est l'étape que la Timeline sait afficher, ou `null` pour celles qui
 * n'en ont pas — `call_agent_gen_pcb` travaille entre l'ERC et le placement
 * sans case dédiée, exactement comme dans l'orchestrateur (`stepMap` la range
 * sous `KICAD`, qui n'est pas dans les étapes affichables).
 */
interface Etape {
  outil: string;
  ui: 'SCHEMA' | 'ERC' | 'PLACEMENT' | 'ROUTING' | 'DRC' | 'EXPORT' | null;
  entree?: Record<string, unknown>;
}

/**
 * ⚠️ L'ORDRE EST LE CONTRAT, et il n'est pas négociable.
 *
 * `gen_pcb` doit précéder le placement : `handlePlacement` lit le board du
 * cache et ne le régénère pas. Le 2026-07-27, il le RÉGÉNÉRAIT et écrasait
 * celui que `gen_pcb` venait de produire — défaut invisible aux tests mockés,
 * révélé seulement en faisant tourner la chaîne contre le service réel.
 *
 * Garde : `tests/run-driver.test.ts` compare la liste des appels.
 */
const CHAINE: Etape[] = [
  { outil: 'call_agent_schema', ui: 'SCHEMA' },
  { outil: 'call_agent_erc', ui: 'ERC', entree: { auto_fix: true } },
  { outil: 'call_agent_gen_pcb', ui: null },
  { outil: 'call_agent_placement', ui: 'PLACEMENT' },
  { outil: 'call_agent_routing', ui: 'ROUTING' },
  { outil: 'call_agent_drc', ui: 'DRC', entree: { auto_fix: true } },
  { outil: 'call_agent_export', ui: 'EXPORT' },
];

function messageDErreur(resultat: Record<string, unknown>, outil: string): string {
  const brut = resultat['error'] ?? resultat['note'];
  return typeof brut === 'string' && brut.length > 0
    ? `${outil} : ${brut}`
    : `${outil} a échoué sans en dire la cause.`;
}

export async function* runDriver(options: DriverOptions): AsyncGenerator<SSEEvent> {
  const { schema, projectId } = options;

  if (!schema || typeof schema !== 'object') {
    yield { type: 'error', message: 'Aucun schéma fourni au porteur du driver.' };
    return;
  }

  yield {
    type: 'text',
    delta: 'Schéma fourni par le driver — la chaîne tourne sans appeler de modèle.\n',
  };

  for (const etape of CHAINE) {
    if (etape.ui) yield { type: 'step', step: etape.ui };

    const entree: Record<string, unknown> = { ...(etape.entree ?? {}) };
    if (etape.outil === 'call_agent_schema') entree['schema_json'] = schema;

    const resultat = await executeToolStub(etape.outil, entree, projectId);

    // ⚠️ FAIL FAST. Chaque handler échoue déjà fermé — `DRC_CLEAN` ne peut être
    // émis que par un DRC réellement exécuté et propre, `PCB_LIVRÉ` que par un
    // export ayant produit des fichiers. Le porteur ne doit pas défaire cette
    // garantie en continuant par-dessus une étape morte : un routage en panne
    // laisserait le DRC puis l'export bâtir un succès sur du vide.
    if (resultat['status'] === 'error') {
      const message = messageDErreur(resultat, etape.outil);
      log.error({ projectId, outil: etape.outil }, 'chaîne du driver interrompue');
      yield { type: 'error', message };
      return;
    }

    const raisonnement = resultat['reasoning_steps'];
    if (Array.isArray(raisonnement) && raisonnement.length > 0) {
      yield { type: 'reasoning', steps: raisonnement.map(String) };
    }

    // Le résultat du handler EST l'état : on ne réécrit pas son statut. C'est
    // précisément ce que `local-pipeline.ts` faisait — un statut codé en dur par
    // étape — et qui persistait `DRC_CLEAN` sur un DRC en erreur.
    yield { type: 'pcb_state', projectId, state: resultat };
  }

  yield { type: 'done', fullText: 'Pipeline du driver terminé.' };
}
