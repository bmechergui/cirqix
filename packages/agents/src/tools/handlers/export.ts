import { pcbStateCache, log } from '../shared';
import { runRealExport, ExportServiceUnavailableError } from '../../engines/export-service';

/**
 * Aucun Gerber n'a été produit → échec explicite.
 *
 * Deux fabrications distinctes vivaient sur ces chemins :
 *   - `pcb_status: 'PCB_LIVRÉ'`, qui fait partie du gate de
 *     POST /api/jlcpcb/order — donc une commande autorisée sans aucun Gerber ;
 *   - `quote_usd: 12.5` et `gerber_layers: 7`, des valeurs INVENTÉES présentées
 *     comme réelles, assorties d'une note invitant à répondre « OUI JE CONFIRME ».
 *     ExportView distingue pourtant déjà un vrai devis d'un placeholder via
 *     `quoteIsReal = state.quoteUsd != null` : ce montant fabriqué défaisait
 *     précisément cette logique.
 *
 * Le BOM CSV est conservé : il dérive du schéma en cache, c'est une donnée
 * réelle et non une fabrication. Il ne s'accompagne d'aucune promotion de statut.
 */
function exportFailure(cause: string, bomCsv: string): Record<string, unknown> {
  return {
    status: 'error',
    error: cause,
    bom_csv: bomCsv,
    note:
      `Export impossible — aucun Gerber produit (${cause}). Le BOM CSV reste ` +
      'disponible. Vérifie que le conteneur Docker KiCad tourne (KICAD_SERVICE_URL).',
  };
}

export async function handleExport(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const schema = cached?.schema ?? { components: [], nets: [] };
  const pcbContent = cached?.kicad_pcb_content;

  // BOM CSV dérivé du schéma en cache — toujours disponible, toujours réel.
  const bomCsv = `ref,value,lcsc\n${schema.components
    .map((c) => `${c.ref},${c.value},${c.lcsc ?? ''}`)
    .join('\n')}`;

  if (!pcbContent || pcbContent.length === 0) {
    return exportFailure('aucun .kicad_pcb en cache — lance le pipeline d\'abord', bomCsv);
  }

  try {
    const result = await runRealExport({
      kicadPcbContent: pcbContent,
      projectId,
    });
    // Un export sauté n'a produit aucun fichier — il ne peut pas livrer le PCB.
    if (result.skipped) {
      log.error({ projectId, warning: result.warning }, 'export skipped — no gerbers produced');
      return exportFailure(result.warning ?? 'kicad-cli indisponible', bomCsv);
    }
    return {
      status: 'success',
      pcb_status: 'DRC_CLEAN',
      gerber_layers: result.files.length,
      files: result.files,
      zip_b64: result.zipB64,
      bom_csv: bomCsv,
      quote_usd: result.quoteUsd,
      lead_time_days: result.leadTimeDays,
      engine: 'kicad-cli',
      note: `Export prêt — ${result.files.length} fichiers (${result.files.join(', ')}). Estimation: $${result.quoteUsd} (${result.leadTimeDays} jours). Aucun ordre n'a été envoyé.`,
    };
  } catch (err) {
    if (!(err instanceof ExportServiceUnavailableError)) {
      log.warn({ err }, 'export service threw unexpected error');
    }
    return exportFailure(
      err instanceof Error ? err.message : 'service export indisponible',
      bomCsv,
    );
  }
}
