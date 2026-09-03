import { pcbStateCache, log, getProjectPlan } from '../shared';
import { maxLayersForPlan } from '@cirqix/types';
import { runPCBEngine } from '../../engines/engine-router';
import { runRealRouting, RoutingServiceUnavailableError } from '../../engines/routing-service';
import { stripTrackSegments, addGroundPlane } from '../pcb-helpers';

/**
 * Aucun routage n'a eu lieu → échec explicite.
 *
 * Ces chemins renvoyaient auparavant `routed_percent: 100` avec un simple plan
 * de masse. Conséquence : shouldRescueRouting ET shouldRetryPlacement étaient
 * désarmés par ce pourcentage fantôme, et l'orchestrateur enchaînait sur
 * DRC/export en annonçant un board « routé à 100% » qui n'avait aucune piste.
 * Un board sans piste n'est pas livrable — même contrat que handlePlacement :
 * fail fast, cache laissé intact pour ne pas écraser le board placé.
 */
// Indice par défaut : la plupart des échecs de routage viennent du service
// injoignable. Un schéma vide n'est PAS de ceux-là — envoyer l'utilisateur
// inspecter Docker pour un board sans composant l'engage sur une fausse piste.
const SERVICE_HINT =
  'Vérifie que le conteneur Docker KiCad tourne (KICAD_SERVICE_URL).';

function routingFailure(cause: string, hint: string = SERVICE_HINT): Record<string, unknown> {
  return {
    status: 'error',
    error: cause,
    note: `Routage impossible — aucune piste posée. ${hint}`,
  };
}

export async function handleRouting(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const schema = cached?.schema ?? { components: [], nets: [] };
  const boardW = cached?.boardW ?? 50;
  const boardH = cached?.boardH ?? 50;

  // Schéma vide : rien à router n'est PAS un routage 100 %. Un
  // `routed_percent: 100` inventé désarmerait shouldRescueRouting et
  // shouldRetryPlacement — même contrat fail-closed que service down.
  if (schema.components.length === 0) {
    return routingFailure(
      'schéma vide — aucun composant à router',
      'Génère le schéma d\'abord (call_agent_schema) : il n\'y a rien à router.',
    );
  }

  // Le plan donne le PLAFOND ; le service decide du palier reel.
  //
  // ⚠️ Une heuristique decidait ici du nombre de couches — « <= 30 composants
  // et <= 30 nets -> 2 couches » — puis on plafonnait par le plan. Le service
  // recevait donc 2 sur toute carte modeste, et son echelle d escalade
  // (`_layer_ladder`) ne rend qu UN palier dans ce cas : monter a 4 etait
  // structurellement impossible.
  //
  // Mesure du 2026-08-26 : l ESP32 du banc (20 composants, 5 nets) restait a
  // 2 couches et n y arrivait pas — 25 % route, 8 connexions manquantes.
  //
  // L heuristique est une ESTIMATION faite AVANT le routage ; le service
  // escalade sur une MESURE, apres avoir essaye et compte. Preferer la
  // premiere revient a faire primer une supposition sur un fait constate.
  //
  // ⚠️ Le plan reste un PLAFOND : un compte gratuit ne depasse pas 2 couches,
  // quoi que le routage reclame. Un plan absent retombe sur `free` — une
  // omission de plumbing ne doit pas ouvrir de droits.
  const decidedLayers = maxLayersForPlan(getProjectPlan(projectId)) as 2 | 4 | 8;

  // Use the placed .kicad_pcb from cache when call_agent_placement ran first.
  // Regenerate from Circuit-Synth only on a cold cache (e.g. routing called standalone).
  const base = cached?.kicad_pcb_content
    ? { kicad_pcb_content: cached.kicad_pcb_content }
    : await runPCBEngine(schema, boardW, boardH, projectId);

  // Strip TS-generated tracks before routing — they point to pre-placement
  // positions and cause "Track has unconnected end" DRC warnings regardless
  // of whether Freerouting succeeds or we fall back to the TS path.
  const cleanPcbContent = stripTrackSegments(base.kicad_pcb_content);

  // Try Freerouting via the FastAPI microservice. On any failure, fall
  // back to a clean (no dangling tracks) PCB with a GND copper pour.
  try {
    const service = await runRealRouting({
      kicadPcbContent: cleanPcbContent,
      layers: decidedLayers,
    });

    if (service.skipped) {
      log.error({ projectId, warning: service.warning }, 'routing skipped — no traces laid');
      return routingFailure(service.warning ?? 'routing service skipped');
    }

    // Add GND copper pour on B.Cu — ensures GND connectivity when Freerouting
    // can't route it as a trace (common on simple linear component layouts).
    const routedPcb = service.kicadPcbContent ?? cleanPcbContent;
    const finalPcb = addGroundPlane(routedPcb, boardW, boardH);

    // Persist routed .kicad_pcb in cache for downstream tools (DRC, export).
    // Clear drc_clean: a new board is not the one previously DRC-validated.
    if (cached) {
      const { drc_clean: _stale, ...rest } = cached;
      pcbStateCache.set(projectId, { ...rest, kicad_pcb_content: finalPcb });
    }

    // via_count / track_length_mm : omettre plutôt que fabriquer
    // (comps*0.5, nets*15) — une heuristique se lit comme une mesure réelle.
    const success: Record<string, unknown> = {
      status: 'success',
      pcb_status: 'ROUTING_DONE',
      routed_percent: service.routedPercent, // vrai % — déclenche call_agent_reason si <100
      // Couches MESURÉES sur le board livré — pas le type `2 | 4 | 8` de
      // `DesignJson.layers`, qui décrit une DÉCISION bornée par le plan. Le
      // `as 2 | 4 | 8` qui traînait ici affirmait au compilateur une contrainte
      // que la mesure ne garantit pas : un board à 6 couches serait passé pour
      // un 2, 4 ou 8. Aucun effet à l'exécution — mais un refactor s'appuyant
      // sur ce type aurait hérité du mensonge.
      layers: service.layers,
      kicad_pcb_content: finalPcb,
      // ⚠️ Le moteur vient du SERVICE, il n'est plus écrit en dur. La cascade a
      // quatre niveaux : sur un board dense, kicad-tools rend 91 %, sous le
      // seuil, et c'est Freerouting qui livre. Annoncer « kicad-tools » dans ce
      // cas est une attribution fausse, et elle envoie chercher au mauvais
      // endroit. Garde : tests/routing-budget.test.ts.
      engine: service.engine ?? 'inconnu',
      note:
        `Routage ${service.engine ?? 'moteur non identifié'} ` +
        `${service.routedPercent}% — ${schema.nets.length} nets, ` +
        `${service.layers} couches.` +
        (service.routedPercent < 100
          ? ' Nets bloqués → reasoner auto-déclenché par l\'orchestrateur.'
          : ''),
    };
    if (typeof service.viaCount === 'number') {
      success['via_count'] = service.viaCount;
    }
    if (typeof service.trackLengthMm === 'number') {
      success['track_length_mm'] = service.trackLengthMm;
    }
    return success;
  } catch (err) {
    if (!(err instanceof RoutingServiceUnavailableError)) {
      log.warn({ err }, 'routing service threw unexpected error');
    }
    return routingFailure(err instanceof Error ? err.message : 'routing service unavailable');
  }
}
