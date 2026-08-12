import { pcbStateCache, log } from '../shared';
import { runCircuitSynthEngine } from '../../engines/engine-router';
import { buildKicadServiceHeaders } from '../../engines/kicad-service-auth';

export async function handleGenPcb(projectId: string): Promise<Record<string, unknown>> {
  // Ingénieur Layout — génère .kicad_pcb depuis le cache (schema + footprints enrichis)
  const cached = pcbStateCache.get(projectId);
  if (!cached?.schema || cached.schema.components.length === 0) {
    return {
      status: 'error',
      note: 'Aucun schéma en cache — appeler call_agent_schema d\'abord.',
    };
  }

  const { schema, boardW, boardH } = cached;

  // Essaie d'abord le service Python pour un PCB de meilleure qualité
  const serviceUrl = process.env.KICAD_SERVICE_URL;
  let kicadPcbContent: string | null = null;

  if (serviceUrl) {
    try {
      const schB64 = cached.kicad_sch_content
        ? Buffer.from(cached.kicad_sch_content, 'utf-8').toString('base64')
        : undefined;
      const res = await fetch(`${serviceUrl}/pcb/generate`, {
        method: 'POST',
        headers: buildKicadServiceHeaders(),
        body: JSON.stringify({
          components: schema.components,
          nets: schema.nets,
          connections: schema.connections ?? [],
          board_width_mm: boardW,
          board_height_mm: boardH,
          project_id: projectId,
          ...(schB64 ? { kicad_sch_b64: schB64 } : {}),
        }),
        signal: AbortSignal.timeout(60_000),
      });
      if (res.ok) {
        const data = await res.json() as { success: boolean; kicad_pcb_content?: string | null };
        if (data.success && data.kicad_pcb_content) {
          kicadPcbContent = data.kicad_pcb_content;
        }
      }
    } catch {
      log.warn('call_agent_gen_pcb: Python service unavailable — using TS generator');
    }
  }

  // Fallback TS inline via runCircuitSynthEngine (sans service URL = TS pur)
  if (!kicadPcbContent) {
    const tsResult = await runCircuitSynthEngine(schema, boardW, boardH, projectId);
    kicadPcbContent = tsResult.kicad_pcb_content;
  }

  // Un board vide n'est pas un succès. Le service court-circuite ses deux
  // niveaux Python quand aucun .kicad_sch n'est en cache et rend "" ; si le
  // générateur TS de repli rend lui aussi une chaîne vide, annoncer un succès
  // ne fait que déplacer l'échec sur le placement, qui échouera sans cause
  // lisible. Le cache n'est pas écrasé : un board précédent, même imparfait,
  // vaut mieux que rien.
  const finalPcb = kicadPcbContent ?? '';
  if (finalPcb.length === 0) {
    log.error({ projectId }, 'call_agent_gen_pcb: aucun .kicad_pcb produit');
    return {
      status: 'error',
      error: 'aucun .kicad_pcb produit',
      note:
        'Génération PCB impossible — ni le service KiCad ni le générateur TS n\'ont '
        + 'produit de board. Vérifie que call_agent_schema a réussi et que le conteneur '
        + 'Docker KiCad tourne (KICAD_SERVICE_URL).',
    };
  }
  // New board → any prior DRC outcome is stale (export must not PCB_LIVRÉ it).
  const { drc_clean: _stale, ...rest } = cached;
  pcbStateCache.set(projectId, { ...rest, kicad_pcb_content: finalPcb });

  // AUCUN `pcb_status` — générer un layout n'est pas un contrôle électrique.
  //
  // L'intention était juste, l'implémentation la trahissait : émettre
  // `SCHEMA_DONE` RÉTROGRADAIT le projet quand l'ERC venait de le porter à
  // `ERC_CLEAN`. Le pont persiste le statut reçu, donc la base et l'interface
  // affichaient un recul — et si le run mourait ici, le contrôle électrique
  // déjà passé était oublié. Un statut qui ment sur ce qui a été vérifié, la
  // même famille de défaut que les succès fabriqués.
  //
  // Ne rien émettre est la traduction exacte de « je ne change pas l'état de
  // validation » : le pont retombe sur `lastStatus` (`raw.pcb_status ??
  // lastStatus`), donc `SCHEMA_DONE` reste `SCHEMA_DONE` et `ERC_CLEAN` reste
  // `ERC_CLEAN`.
  //
  // Trouvé le 2026-08-12 par un audit externe (Grok).
  return {
    status: 'success',
    kicad_pcb_content: finalPcb,
    board_width_mm: boardW,
    board_height_mm: boardH,
    component_count: schema.components.length,
    note: `PCB généré — ${schema.components.length} composants, board ${boardW}×${boardH} mm. Prêt pour placement.`,
  };
}
