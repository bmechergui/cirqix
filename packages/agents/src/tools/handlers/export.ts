import { pcbStateCache, log } from '../shared';
import { runRealExport, ExportServiceUnavailableError } from '../../engines/export-service';

export async function handleExport(projectId: string): Promise<Record<string, unknown>> {
  const cached = pcbStateCache.get(projectId);
  const schema = cached?.schema ?? { components: [], nets: [] };
  const pcbContent = cached?.kicad_pcb_content;
  const hasOfficialDrc = cached?.drc_clean === true
    && cached.drc_skipped !== true
    && cached.drc_validation === 'kicad-cli';

  // Always-available fallback BOM CSV from the cached schema components
  const fallbackBomCsv = `ref,value,lcsc\n${schema.components
    .map((c) => `${c.ref},${c.value},${c.lcsc ?? ''}`)
    .join('\n')}`;

  if (!hasOfficialDrc) {
    return {
      status: 'error',
      pcb_status: 'ROUTING_DONE',
      gerber_layers: 0,
      engine: 'drc-gate',
      warning: 'Official KiCad DRC evidence is required before export.',
      note: 'Export blocked until the official KiCad DRC passes with zero errors.',
    };
  }

  if (!pcbContent || pcbContent.length === 0) {
    return {
      status: 'error',
      pcb_status: 'ROUTING_DONE',
      gerber_layers: 0,
      engine: 'fallback-skip',
      warning: 'No .kicad_pcb in cache — run the pipeline first.',
      note: 'Export sauté — pas de PCB en cache.',
    };
  }

  try {
    const result = await runRealExport({
      kicadPcbContent: pcbContent,
      projectId,
    });
    if (result.skipped) {
      return {
        status: 'error',
        pcb_status: 'ROUTING_DONE',
        gerber_layers: 0,
        engine: 'kicad-cli-skipped',
        warning: result.warning,
        note: `Export sauté — ${result.warning ?? 'kicad-cli indisponible'}. BOM CSV fallback inclus. Confirme avec "OUI JE CONFIRME" pour commander en production.`,
      };
    }
    return {
      status: 'success',
      pcb_status: 'DRC_CLEAN',
      gerber_layers: result.files.length,
      files: result.files,
      zip_b64: result.zipB64,
      bom_csv: fallbackBomCsv,
      quote_usd: result.quoteUsd,
      lead_time_days: result.leadTimeDays,
      engine: 'kicad-cli',
      note: `Export prêt — ${result.files.length} fichiers (${result.files.join(', ')}). Devis: $${result.quoteUsd} (${result.leadTimeDays} jours). Confirme avec "OUI JE CONFIRME".`,
    };
  } catch (err) {
    if (!(err instanceof ExportServiceUnavailableError)) {
      log.warn({ err }, 'export service threw unexpected error — falling back');
    }
    return {
      status: 'error',
      pcb_status: 'ROUTING_DONE',
      gerber_layers: 0,
      engine: 'fallback-skip',
      warning: err instanceof Error ? err.message : 'export service unavailable',
      note: 'Export fallback — BOM CSV uniquement. Gerbers générés en production. Confirme avec "OUI JE CONFIRME".',
    };
  }
}
