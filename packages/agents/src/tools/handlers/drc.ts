import { pcbStateCache, log } from '../shared';
import { runRealDrc, DrcServiceUnavailableError } from '../../engines/drc-service';

/**
 * Le DRC n'a pas pu statuer → échec explicite.
 *
 * `pcb_status: 'DRC_CLEAN'` n'est pas un simple libellé : orchestrator-bridge le
 * persiste dans projects.status et POST /api/jlcpcb/order refuse toute commande
 * dont le statut n'est pas DRC_CLEAN. Ces chemins renvoyaient auparavant
 * DRC_CLEAN + drc_clean:true sans qu'aucun DRC n'ait tourné — kicad-cli absent
 * ou KICAD_SERVICE_URL non configurée suffisait donc à débloquer la commande
 * JLCPCB sur une carte jamais verifiée. « On n'a pas pu vérifier » n'est pas
 * « c'est propre ». Même contrat de fail fast que handlePlacement/handleRouting.
 */
function drcFailure(cause: string): Record<string, unknown> {
  return {
    status: 'error',
    error: cause,
    note:
      `DRC impossible — le board n'a PAS été validé (${cause}). Vérifie que le ` +
      'conteneur Docker KiCad tourne (KICAD_SERVICE_URL).',
  };
}

export async function handleDrc(
  input: Record<string, unknown>,
  projectId: string
): Promise<Record<string, unknown>> {
  const autoFix = input['auto_fix'] !== false; // default true
  const cached = pcbStateCache.get(projectId);
  const pcbContent = cached?.kicad_pcb_content;
  if (!pcbContent || pcbContent.length === 0) {
    return drcFailure('aucun .kicad_pcb en cache — lance call_agent_routing d\'abord');
  }

  try {
    const result = await runRealDrc({ kicadPcbContent: pcbContent, autoFix });

    // Un DRC sauté n'a rien validé — il ne peut pas promouvoir DRC_CLEAN.
    if (result.skipped) {
      log.error({ projectId, warning: result.warning }, 'DRC skipped — board not validated');
      return drcFailure(result.warning ?? 'kicad-cli indisponible');
    }

    // Only promote to DRC_CLEAN when the board is actually clean.
    // Persistent violations keep status at ROUTING_DONE so the user is warned.
    const newStatus: 'DRC_CLEAN' | 'ROUTING_DONE' = result.drcClean ? 'DRC_CLEAN' : 'ROUTING_DONE';
    const finalPcb = result.kicadPcbContent ?? pcbContent;

    // Persist board + DRC outcome for export: handleExport must not invent a
    // validation status — it only reads `drc_clean` written here.
    if (cached) {
      pcbStateCache.set(projectId, {
        ...cached,
        kicad_pcb_content: finalPcb,
        drc_clean: result.drcClean,
      });
    }

    return {
      status: 'success',
      pcb_status: newStatus,
      drcViolations: result.violations,
      drc_clean: result.drcClean,
      drc_skipped: false,
      fixed_count: result.fixedCount,
      kicad_pcb_content: finalPcb,
      engine: 'kicad-cli',
      warning: result.warning,
      note: result.drcClean
        ? `DRC OK — 0 violation${result.fixedCount > 0 ? `, ${result.fixedCount} auto-fix appliqués` : ''}.`
        : `DRC — ${result.violations.length} violations restantes après auto-fix.`,
    };
  } catch (err) {
    if (!(err instanceof DrcServiceUnavailableError)) {
      log.warn({ err }, 'DRC service threw unexpected error');
    }
    return drcFailure(err instanceof Error ? err.message : 'service DRC indisponible');
  }
}
